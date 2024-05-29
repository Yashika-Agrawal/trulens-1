"""Spans

These are roughly equivalent to `RecordAppCall` but abstract away specific method
information into type of call related to types of components.
"""

from __future__ import annotations

import dataclasses
import datetime
from enum import Enum
from logging import getLogger
from typing import Annotated, Any, Callable, Dict, Generic, List, Optional, Type, TypeVar

import opentelemetry.trace.span as ot_span

from opentelemetry.util import types as ot_types
import pandas as pd
import pydantic_core
import pydantic
from pydantic import computed_field
from pydantic import Field
from pydantic import TypeAdapter, PlainValidator
from pydantic_core import core_schema as cs
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler, TypeAdapter
from pydantic.json_schema import JsonSchemaValue
import json


from trulens_eval import trace as mod_trace
from trulens_eval.schema import record as mod_record_schema
from trulens_eval.utils.serial import JSON
from trulens_eval.utils import containers as mod_container_utils

logger = getLogger(__name__)

T = TypeVar("T")

class AttributeProperty(property, Generic[T]):
    """Property that stores its value in the attributes dictionary with a
    vendor prefix.
    
    This is meant to be used only in SpanType instances (or subclasses).
    """

    def __init__(
        self,
        name: str,
        typ: Optional[Type[T]] = None,
        typ_factory: Optional[Callable[[], Type[T]]] = None,
        default: Optional[T] = None,
        default_factory: Optional[Callable[[], T]] = None
    ):
        self.name = name
        self.typ = typ
        self.typ_factory = typ_factory
        self.default = default
        self.default_factory = default_factory

        self.forward_initialized = False

    def init_forward(self):
        if self.forward_initialized:
            return

        self.forward_initialized = True

        if self.typ is None and self.typ_factory is not None:
            self.typ = self.typ_factory()

        if self.default is None and self.default_factory is not None:
            self.default = self.default_factory()

        if self.typ is None and self.default is not None:
            self.typ = type(self.default)

        if self.typ is None:
            self.tadapter = None
        else:
            self.tadapter = TypeAdapter(self.typ)
            if self.default is not None:
                self.tadapter.validate_python(self.default)
    
    def __get__(self, obj, objtype) -> Optional[T]:
        if obj is None:
            return self

        self.init_forward()
        return obj.attributes.get(obj.vendor_attr(self.name), self.default)

    def __set__(self, obj, value: T) -> None:
        self.init_forward()

        if self.tadapter is not None:
            self.tadapter.validate_python(value)

        obj.attributes[obj.vendor_attr(self.name)] = value

    def __delete__(self, obj):
        del obj.attributes[obj.vendor_attr(self.name)]

    def __set_name__(self, cls, name):
        if name in cls.__annotations__:
            # If type is specified in annotation, take it from there.
            self.typ = cls.__annotations__[name]
            self.tadapter = TypeAdapter(self.typ)

            # Update the recorded return type as well.
            # TODO: cannot do this at this point as the below dict is not yet populated
            # if name in cls.model_computed_fields:
            #     cls.model_computed_fields[name].return_type = self.typ

            # Have to remove it as pydantic will complain about overriding fields with computed fields.
            del cls.__annotations__[name]

class Span(mod_trace.OTSpan):
    """Base Span type.
    
    Smallest unit of recorded activity.
    """

    @staticmethod
    def attribute_property(
        name: str,
        typ: Optional[Type[T]] = None,
        typ_factory: Optional[Callable[[], Type[T]]] = None,
        default: Optional[T] = None,
        default_factory: Optional[Callable[[], T]] = None
    ) -> property:
        """Utility for creating properties that store their values in the
        attributes dictionary with a vendor prefix.

        Validates default and on assignment.

        TODO: Make sure pydantic can generate the schema for these.
        
        Args:
            name: The name of the property. The key used for storage will be
                this with the vendor prefix.

            typ: The type of the property.

            typ_factory: A factory function that returns the type of the
                property. This can be used for forward referenced types.

            default: The default value of the property.

            default_factory: A factory function that returns the default value
                of the property. This can be used for defaults that make use of
                forward referenced types.
        """

        return computed_field(
            AttributeProperty(name, typ, typ_factory, default, default_factory),
            return_type=typ
        )

    @property
    def start_datetime(self) -> datetime.datetime:
        """Start time of span as a [datetime][datetime.datetime]."""
        return mod_container_utils.datetime_of_ns_timestamp(self.start_timestamp)
    
    @start_datetime.setter
    def start_datetime(self, value: datetime.datetime):
        self.start_timestamp = mod_container_utils.ns_timestamp_of_datetime(value)

    @property
    def end_datetime(self) -> datetime.datetime:
        """End time of span as a [datetime][datetime.datetime]."""
        return mod_container_utils.datetime_of_ns_timestamp(self.end_timestamp)
    
    @end_datetime.setter
    def end_datetime(self, value: datetime.datetime):
        self.end_timestamp = mod_container_utils.ns_timestamp_of_datetime(value)

    @property
    def span_id(self) -> mod_trace.TSpanID:
        """Identifier for the span."""

        return self.context.span_id

    @property
    def trace_id(self) -> mod_trace.TTraceID:
        """Identifier for the trace this span belongs to."""

        return self.context.trace_id

    @property # want # @functools.cached_property but those are not allowed to have setters
    def parent_context(self) -> Optional[ot_span.SpanContext]:
        """Context of parent span if any.

        This is stored in OT links with a relationship attribute of "parent".
        None if this is a root span or otherwise it does not have a parent.
        """

        for link_context, link_attributes in self.links.items():
            if link_attributes.get(self.vendor_attr("relationship")) == "parent":
                return link_context

        return None

    @parent_context.setter
    def parent_context(self, value: Optional[ot_span.SpanContext]):
        if value is None:
            return

        if self.parent_context is not None:
            # Delete existing parent if any.
            del self.links[self.parent_context]

        self.add_link(value, {self.vendor_attr("relationship"): "parent"})

    # want functools.cached_property but need updating due to the above setter
    @property
    def parent_span_id(self) -> Optional[mod_trace.TSpanID]:
        """Id of parent span if any."""

        parent_context = self.parent_context
        if parent_context is not None:
            return parent_context.span_id

        return None

    tags = attribute_property(
        "tags", typ=List[str], default_factory=list
    )
    """Tags associated with the span."""

    span_type = attribute_property(
        "span_type",
        typ_factory=lambda: SpanType,
        default_factory=lambda: SpanType.UNTYPED
    )
    """Type of span."""

    attributes_metadata: mod_container_utils.DictNamespace[ot_types.AttributeValue]
    # will be set as a DictNamespace indexing elements in attributes
    @property
    def metadata(self) -> mod_container_utils.DictNamespace[ot_types.AttributeValue]:
        return self.attributes_metadata

    @metadata.setter
    def metadata(self, value: Dict[str, str]):
        for k, v in value.items():
            self.attributes_metadata[k] = v

    def __init__(self, **kwargs):
        kwargs['attributes_metadata'] = mod_container_utils.DictNamespace(parent={}, namespace="temp")
        # Temporary fake for validation in super.__init__ below.

        super().__init__(**kwargs)

        # Actual. This is needed as pydantic will copy attributes dict in init.
        self.attributes_metadata = mod_container_utils.DictNamespace(
            parent=self.attributes,
            namespace=self.vendor_attr("metadata")
        )

        self.set_attribute(self.vendor_attr("span_type"), self.__class__.__name__)

class SpanUntyped(Span):
    """Generic span type.
    
    This represents spans that are being recorded but have not yet been
    determined to be of a particular type.
    """

class TransSpanRecord(Span):
    """A span whose activity was recorded in a record.
    
    Features references to the record.

    !!! note
        This is a transitional type for the traces work.
    """

    record: Annotated[
        mod_record_schema.Record,
        pydantic.WithJsonSchema(None)
    ] = Field(exclude=True, default=None)
    record_id = Span.attribute_property("record_id", typ=str, default=None)

class SpanMethodCall(TransSpanRecord):
    """Span which corresponds to a method call.
    
    See also temporary development attributes in
    [TransSpanRecordAppCall][trulens_eval.trace.span.TransSpanRecordCall].
    """

    inputs = Span.attribute_property("inputs", typ=Optional[Dict[str, Any]], default_factory=None)
    # TODO: Need to encode to OT AttributeValue

    output = Span.attribute_property("output", typ=Optional[JSON], default_factory=None)
    # TODO: Need to encode to OT AttributeValue

    error = Span.attribute_property("error", typ=Optional[Any], default_factory=None)
    # TODO: Need to encode to OT AttributeValue


class TransSpanRecordAppCall(SpanMethodCall):
    """A Span which corresponds to single
    [RecordAppCall][trulens_eval.schema.record.RecordAppCall].

    Features references to the call.

    !!! note
        This is a transitional type for the traces work. The non-transitional
        fields are being placed in
        [SpanMethodCall][trulens_eval.trace.span.SpanMethodCall] instead.
    """
    call: Annotated[
        mod_record_schema.RecordAppCall,
         pydantic.WithJsonSchema(None)
    ] = Field(exclude=True, default=None)

class SpanRoot(TransSpanRecord):
    """A root span encompassing some collection of spans.

    Does not indicate any particular activity by itself beyond its children.
    """

SpanTyped = TransSpanRecordAppCall
"""Alias for the superclass of spans that went through the record call conversion."""

"""
@dataclasses.dataclass
class RetrieverQuery:
    text: str
    embedding: Optional[List[float]]

@dataclasses.dataclass
class RetrieverContext:
    text: str
    score: Optional[float]
    embedding: Optional[List[float]]
"""

class SpanRetriever(SpanTyped):
    """A retrieval."""

    query_text = Span.attribute_property("query_text", str)
    """Input text whose related contexts are being retrieved."""

    query_embedding = Span.attribute_property("query_embedding", List[float])
    """Embedding of the input text."""

    distance_type = Span.attribute_property("distance_type", str)
    """Distance function used for ranking contexts."""

    num_contexts = Span.attribute_property("num_contexts", int)
    """The number of contexts requested, not necessarily retrieved."""

    retrieved_contexts = Span.attribute_property("retrieved_contexts", List[str])
    """The retrieved contexts."""

    retrieved_scores = Span.attribute_property("retrieved_scores", List[float])
    """The scores of the retrieved contexts."""

    retrieved_embeddings = Span.attribute_property("retrieved_embeddings", List[List[float]])
    """The embeddings of the retrieved contexts."""

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: cs.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema = handler.resolve_ref_schema(json_schema)
        json.dumps(json_schema, indent=2)
        return json_schema

class SpanReranker(SpanTyped):
    """A reranker call."""

    query_text = Span.attribute_property("query_text", str)
    """The query text."""

    model_name = Span.attribute_property("model_name", str)
    """The model name of the reranker."""

    top_n = Span.attribute_property("top_n", int)
    """The number of contexts to rerank."""

    input_context_texts = Span.attribute_property("input_context_texts", List[str])
    """The contexts being reranked."""

    input_context_scores = Span.attribute_property("input_context_scores", Optional[List[float]])
    """The scores of the input contexts."""

    output_ranks = Span.attribute_property("output_ranks", List[int])
    """Reranked indexes into `input_context_texts`."""

class SpanLLM(SpanTyped):
    """A generation call to an LLM."""

    model_name = Span.attribute_property("model_name", str)
    """The model name of the LLM."""

    model_type = Span.attribute_property("model_type", str)
    """The type of model used."""

    temperature = Span.attribute_property("temperature", float)
    """The temperature used for generation."""

    input_messages = Span.attribute_property("input_messages", List[dict])
    """The prompt given to the LLM."""

    input_token_count = Span.attribute_property("input_token_count", int)
    """The number of tokens in the input."""

    output_messages = Span.attribute_property("output_messages", List[dict])
    """The returned text."""

    output_token_count = Span.attribute_property("output_token_count", int)
    """The number of tokens in the output."""

    cost = Span.attribute_property("cost", float)
    """The cost of the generation."""

class SpanMemory(SpanTyped):
    """A memory call."""

    memory_type = Span.attribute_property("memory_type", str)
    """The type of memory."""

    remembered = Span.attribute_property("remembered", str)
    """The text being integrated into the memory in this span."""

class SpanEmbedding(SpanTyped):
    """An embedding cal."""

    input_text = Span.attribute_property("input_text", str)
    """The text being embedded."""

    model_name = Span.attribute_property("model_name", str)
    """The model name of the embedding model."""

    embedding = Span.attribute_property("embedding", List[float])
    """The embedding of the input text."""

class SpanTool(SpanTyped):
    """A tool invocation."""

    description = Span.attribute_property("description", str)
    """The description of the tool."""

class SpanAgent(SpanTyped):
    """An agent invocation."""

    description = Span.attribute_property("description", str)
    """The description of the agent."""

class SpanTask(SpanTyped):
    """A task invocation."""

class SpanOther(SpanTyped):
    """Other uncategorized spans."""

class SpanType(Enum):
    """Span types.
    
    This is a bit redundant with the span type hierarchy above. It is here for
    convenience of looking up types in means other than `__class__` or via
    `isinstance`.
    """

    def to_class(self) -> Type[Span]:
        """Convert to the class for this type."""

        if hasattr(mod_trace.span, self.value):
            return getattr(mod_trace.span, self.value)
        
        raise ValueError(f"Span type {self.value} not found in module.")

    UNTYPED = SpanUntyped.__name__
    """See [SpanUntyped][trulens_eval.trace.span.SpanUntyped]."""

    ROOT = SpanRoot.__name__
    """See [SpanRoot][trulens_eval.trace.span.SpanRoot]."""

    RETRIEVER = SpanRetriever.__name__
    """See [SpanRetriever][trulens_eval.trace.span.SpanRetriever]."""

    RERANKER = SpanReranker.__name__
    """See [SpanReranker][trulens_eval.trace.span.SpanReranker]."""

    LLM = SpanLLM.__name__
    """See [SpanLLM][trulens_eval.trace.span.SpanLLM]."""

    MEMORY = SpanMemory.__name__
    """See [SpanMemory][trulens_eval.trace.span.SpanMemory]."""

    EMBEDDING = SpanEmbedding.__name__
    """See [SpanEmbedding][trulens_eval.trace.span.SpanEmbedding]."""

    TOOL = SpanTool.__name__
    """See [SpanTool][trulens_eval.trace.span.SpanTool]."""

    AGENT = SpanAgent.__name__
    """See [SpanAgent][trulens_eval.trace.span.SpanAgent]."""

    TASK = SpanTask.__name__
    """See [SpanTask][trulens_eval.trace.span.SpanTask]."""

    OTHER = SpanOther.__name__
    """See [SpanOther][trulens_eval.trace.span.SpanOther]."""
