import asyncio
from typing import Optional

from trulens_eval.schema import app as mod_app_schema
from trulens_eval.schema import record as mod_record_schema
from trulens_eval.tru import Tru
from trulens_eval.utils.json import jsonify_for_ui
from trulens_eval.utils.serial import JSON
from trulens_eval.utils.serial import Lens
from trulens_eval.utils.streamlit import init_from_args
from trulens_eval.ux.apps import ChatRecord

# https://github.com/jerryjliu/llama_index/issues/7244:
asyncio.set_event_loop(asyncio.new_event_loop())
import streamlit as st
from ux.page_config import set_page_config

if __name__ == "__main__":
    # If not imported, gets args from command line and creates Tru singleton
    init_from_args()

tru = Tru()
lms = tru.db

st.runtime.legacy_caching.clear_cache()

set_page_config(page_title="App Runner")


def remove_selector(
    container,
    type: str,  # either "app" or "record"
    selector_idx: int,
    record_idx: int,
    selector: str,
    rec: Optional[ChatRecord] = None
):
    """
    Remove the `selector` of type `type`. A selector should be uniquely
    addressed/keyed by `type`, `selector_idx`, and `record_idx` but don't
    presently see a reason to have duplicate selectors so indexing only by
    `type` and `selector` for now. `container` is the streamlit "empty" object
    that contains the widgets for this selector. For `record` types,
    `record_idx` is ignored as the selector is removed from all of the
    rows/records.
    """

    state = st.session_state[f"selectors_{type}"]

    if selector in state:
        state.remove(selector)
    else:
        print("no such selector")
        return

    # Get and delete all of the containers for this selector. If this is a
    # record `type`, there will be one container for each record row.
    key_norec = f"{type}_{selector_idx}"
    for container in st.session_state[f"containers_{key_norec}"]:
        del container


def update_selector(
    container,
    type: str,
    selector_idx: int,
    record_idx: int,
    selector: str,
    rec: Optional[ChatRecord] = None
):
    """
    Update the selector keyed by `type`, `selector_idx`, `record_idx` to the new
    value retrieved from state. Only works assuming selectors are unique within
    each `type`.
    """

    state = st.session_state[f"selectors_{type}"]

    key = f"{type}_{selector_idx}_{record_idx}"

    new_val = st.session_state[f"edit_input_{key}"]

    state[state.index(selector)] = new_val


def draw_selector(
    type: str,
    selector_idx: int,
    record_idx: int,
    selector: str,
    rec: Optional[ChatRecord] = None
):
    """
    Draws the UI elements for a selector of type `type` intended to be keyed by
    (type) and `selector_idx` and `record_idx`. The selector represents a
    Lens given as str in `selector`. Includes delete and edit widgets as
    well as the listing of the values attained by the selected path in the given
    ChatRecord `rec`. 
    """

    key = f"{type}_{selector_idx}_{record_idx}"
    key_norec = f"{type}_{selector_idx}"

    container = st.empty()

    # Add the container for these elements into the state indexed by type and
    # selector so we can easily delete it later alongside its analogues in order
    # records (for "record" `type` selectors).
    if f"containers_{key_norec}" not in st.session_state:
        st.session_state[f"containers_{key_norec}"] = []
    st.session_state[f"containers_{key_norec}"].append(container)

    # Cannot stack columns too deeply:
    #c1, c2 = st.columns(2)

    # TODO: figure out how to expand/collapse these across all records at the
    # same time, this session thing does not work.
    st.session_state[f"expanded_{key_norec}"] = True

    # Put everything in this expander:
    exp = container.expander(
        label=selector, expanded=st.session_state[f"expanded_{key_norec}"]
    )

    # Edit input.
    exp.text_input(
        label="App selector",
        value=selector,
        key=f"edit_input_{key}",
        on_change=update_selector,
        kwargs=dict(
            container=container,
            type=type,
            selector_idx=selector_idx,
            record_idx=record_idx,
            selector=selector,
            rec=rec
        ),
        label_visibility="collapsed"
    )

    # Get the relevant JSON to path into.
    obj = rec.app_json
    if type == "record":
        obj = mod_record_schema.Record.model_validate(rec.record_json
                                                     ).layout_calls_as_app()
