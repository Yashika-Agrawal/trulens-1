"""
# NEMO Guardrails instrumentation and monitoring. 
"""

import inspect
from inspect import BoundArguments
from inspect import Signature
import logging
from pprint import pformat
from pprint import pprint
from typing import Any, Callable, ClassVar, Dict, List, Optional

from langchain_core.language_models.base import BaseLanguageModel
from pydantic import Field

from trulens_eval.app import App
from trulens_eval.instruments import Instrument
from trulens_eval.schema import Select
from trulens_eval.tru_chain import LangChainInstrument
from trulens_eval.utils.containers import dict_set_with_multikey
from trulens_eval.utils.imports import OptionalImports
from trulens_eval.utils.imports import REQUIREMENT_RAILS
from trulens_eval.utils.json import jsonify
from trulens_eval.utils.pyschema import Class
from trulens_eval.utils.pyschema import FunctionOrMethod
from trulens_eval.utils.python import safe_hasattr
from trulens_eval.utils.serial import JSON
from trulens_eval.utils.serial import Lens
from trulens_eval.utils.text import retab

logger = logging.getLogger(__name__)

with OptionalImports(messages=REQUIREMENT_RAILS):
    import nemoguardrails
    from nemoguardrails import LLMRails
    from nemoguardrails import RailsConfig
    from nemoguardrails.actions.action_dispatcher import ActionDispatcher
    from nemoguardrails.actions.actions import action
    from nemoguardrails.actions.actions import ActionResult
    from nemoguardrails.actions.llm.generation import LLMGenerationActions
    from nemoguardrails.flows.runtime import Runtime
    from nemoguardrails.kb.kb import KnowledgeBase
    from nemoguardrails.rails.llm.llmrails import LLMRails
    
OptionalImports(messages=REQUIREMENT_RAILS).assert_installed(nemoguardrails)


class RailsActionSelect(Select):
    """
    Selector shorthands for NEMO guardrails apps when used for evaluating
    feedback in actions. These should not be used for feedback functions given
    to `TruRails`.
    """

    Action = Lens().action

    # default action function arguments
    Events = Action.events
    Context = Action.context # NOTE: this is not the same "context" as in RAG
    LLM = Action.llm
    Config = Action.config

    RetrievalContexts = Context.relevant_chunks_sep

    UserMessage = Context.user_message
    BotMessage = Context.bot_message

    LastUserMessage = Context.last_user_message
    LastBotMessage = Context.last_bot_message


# NOTE(piotrm): Cannot have this inside FeedbackActions presently due to perhaps
# some closure-related issues with the @action decorator below.
registered_feedback_functions = {}

class FeedbackActions():
    @staticmethod
    def register_feedback_functions(**kwargs):
        for name, feedback in kwargs.items():
            registered_feedback_functions[name] = feedback

    @action(name="feedback")
    @staticmethod
    async def feedback(
        events: Optional[List[Dict]] = None, 
        context: Optional[Dict] = None,
        llm: Optional[BaseLanguageModel] = None,
        config: Optional[RailsConfig] = None,
        function: Optional[str] = None,
        selectors: Optional[Dict[str, Lens]] = None,
        verbose: bool = False
    ) -> ActionResult:

        """
        Run the specified feedback function from trulens_eval. To use this action,
        it needs to be registered with your rails app and feedback functions
        themselves need to be registered with this function.
        
        ```python
        rails: LLMRails = ... # your app
        relevance_feedback: Feedback = Feedback(...) # your feedback function

        FeedbackAction.register_feedback_functions(relevance=relevance_feedback)
        # Can also use kwargs expansion from dict like produced  by RAG_triad:
        # FeedbackAction.register_feedback_functions(**RAG_triad(...))

        rails.register_action(FeedbackAction)
        ```

        Args:
            - function: str -- the feedback function to run.
            
            - selectors: Dict[str, Union[str, Lens]] -- the selectors for the
            function. Can be provided either as strings to be parsed into lenses
            or lenses themselves.
            
            - verbose: bool -- whether to print the values of the selectors
              before running feedback and print the result after running
              feedback.

            - the other args are action defaults args.

        Returns:
            ActionResult: An action result containing the result of the feedback.

        Note:
            ...

        Example:
            ```colang
                define subflow check language match
                    $result = execute feedback(\
                        function="language_match",\
                        selectors={\
                        "text1":"action.context.last_user_message",\
                        "text2":"action.context.bot_message"\
                        }\
                    )
                    if $result < 0.8
                        bot inform language mismatch
            ```
        """

        feedback_function = registered_feedback_functions.get(function)
        

        if feedback_function is None:
            raise ValueError(
                f"Invalid feedback function: {function}; "
                f"there is/are {len(registered_feedback_functions)} registered function(s):\n\t" + 
                "\n\t".join(registered_feedback_functions.keys()) + "\n"
            )

        fname = feedback_function.name

        if selectors is None:
            raise ValueError(
                f"Need selectors for feedback function: {fname} "
                f"with signature {inspect.signature(feedback_function.imp)}"
            )
        
        selectors = {
            argname: (Lens.of_string(arglens) if isinstance(arglens, str) else arglens)
            for argname, arglens in selectors.items()
        }

        feedback_function = feedback_function.on(**selectors)

        source_data = dict(
            action=dict(events=events, context=context, llm=llm, config=config)
        )

        if verbose:
            print(fname)
            for argname, lens in feedback_function.selectors.items():
                print(f"  {argname} = ", end=None)
                # use pretty print for the potentially big thing here:
                print(retab(tab="    ", s=pformat(lens.get_sole_item(source_data))))
    
        context_updates = {}
        
        try:
            result = feedback_function.run(source_data=source_data)
            context_updates["result"] = result.result

            if verbose:
                print(f"  {fname} result = {result.result}")

        except Exception as e:
            context_updates["result"] = None

            return ActionResult(
                return_value=context_updates["result"],
                context_updates=context_updates,
            )

        return ActionResult(
            return_value=context_updates["result"],
            context_updates=context_updates,
        )


class RailsInstrument(Instrument):

    class Default:
        MODULES = {"nemoguardrails"}.union(
            LangChainInstrument.Default.MODULES
        )  # NOTE: nemo uses langchain internally for some things

        # Putting these inside thunk as llama_index is optional.
        CLASSES = lambda: {
            LLMRails, KnowledgeBase, LLMGenerationActions, Runtime, ActionDispatcher, FeedbackActions
        }.union(LangChainInstrument.Default.CLASSES())

        # Instrument only methods with these names and of these classes. Ok to
        # include llama_index inside methods.
        METHODS = dict_set_with_multikey(
            dict(LangChainInstrument.Default.METHODS), # copy
            {
                ("execute_action"): lambda o: isinstance(o, ActionDispatcher),
                (
                    "generate", "generate_async",
                    "stream_async",
                    "generate_events", "generate_events_async", "_get_events_for_messages"
                ): lambda o: isinstance(o, LLMRails),
                "search_relevant_chunks": lambda o: isinstance(o, KnowledgeBase),
                (
                    "generate_user_intent",
                    "generate_next_step",
                    "generate_bot_message",
                    "generate_value",
                    "generate_intent_steps_message"
                ): lambda o: isinstance(o, LLMGenerationActions),
                (
                    "generate_events",
                    "compute_next_steps"
                ): lambda o: isinstance(o, Runtime),
                "feedback": lambda o: isinstance(o, FeedbackActions),
            }
        )

    def __init__(self, *args, **kwargs):
        super().__init__(
            include_modules=RailsInstrument.Default.MODULES,
            include_classes=RailsInstrument.Default.CLASSES(),
            include_methods=RailsInstrument.Default.METHODS,
            *args,
            **kwargs
        )


class TruRails(App):
    """
    Recorder for apps defined using NEMO guardrails.

        Args:
            app -- A nemo guardrails application.
    """

    model_config: ClassVar[dict] = dict(arbitrary_types_allowed=True)

    app: LLMRails

    root_callable: ClassVar[FunctionOrMethod] = Field(
        default_factory=lambda: FunctionOrMethod.of_callable(LLMRails.generate)
    )

    def __init__(self, app: LLMRails, **kwargs):
        # TruLlama specific:
        kwargs['app'] = app
        kwargs['root_class'] = Class.of_object(app)  # TODO: make class property
        kwargs['instrument'] = RailsInstrument(app=self)

        super().__init__(**kwargs)

    def main_output(
        self, func: Callable, sig: Signature, bindings: BoundArguments, ret: Any
    ) -> JSON:
        """
        Determine the main out string for the given function `func` with
        signature `sig` after it is called with the given `bindings` and has
        returned `ret`.
        """

        if isinstance(ret, dict):
            if "content" in ret:
                return ret['content']

        return jsonify(ret)

    def main_input(
        self, func: Callable, sig: Signature, bindings: BoundArguments
    ) -> JSON:
        """
        Determine the main input string for the given function `func` with
        signature `sig` after it is called with the given `bindings` and has
        returned `ret`.
        """

        if "messages" in bindings.arguments:
            messages = bindings.arguments['messages']
            if len(messages) == 1:
                message = messages[0]
                if "content" in message:
                    return message["content"]

        return jsonify(bindings.arguments)


    @classmethod
    def select_context(
        cls,
        app: Optional[LLMRails] = None
    ) -> Lens:
        """
        Get the path to the context in the query output.
        """
        return Select.RecordCalls.kb.search_relevant_chunks.rets[:].body

    def __getattr__(self, __name: str) -> Any:
        # A message for cases where a user calls something that the wrapped
        # app has but we do not wrap yet.

        if safe_hasattr(self.app, __name):
            return RuntimeError(
                f"TruRails has no attribute {__name} but the wrapped app ({type(self.app)}) does. ",
                f"If you are calling a {type(self.app)} method, retrieve it from that app instead of from `TruRails`. "
            )
        else:
            raise RuntimeError(f"TruRails has no attribute named {__name}.")

TruRails.model_rebuild()