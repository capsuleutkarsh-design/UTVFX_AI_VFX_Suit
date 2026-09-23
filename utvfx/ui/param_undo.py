"""Undoable parameter edits from the UI.

Every user edit goes through the window's QUndoStack as a ChangeParamCommand.
Structured values (the SuperMatte "mask_layers" list) are deep-copied in and out
of the command, so later in-place edits never change what undo restores.
"""
import copy

from utvfx.core.commands import ChangeParamCommand


class DeepParamCommand(ChangeParamCommand):
    """ChangeParamCommand for lists and dicts: stores and sets private deep copies."""

    def __init__(self, node, param_id, old_val, new_val, description="Change Parameter"):
        super().__init__(node, param_id, copy.deepcopy(old_val), copy.deepcopy(new_val), description)

    def _set(self, value):
        super()._set(copy.deepcopy(value))


def undo_stack_for(node):
    scene = node.scene() if node is not None and hasattr(node, "scene") else None
    return getattr(scene, "undo_stack", None) if scene is not None else None


def _values_equal(a, b):
    try:
        return bool(a == b)
    except Exception:
        return False


def push_param(node, param_id, old_val, new_val, description=None, deep=False):
    """Set node.params[param_id] = new_val through undo. Returns False when nothing changed."""
    if node is None or _values_equal(old_val, new_val):
        return False
    if not hasattr(node, "params"):
        node.params = {}
    description = description or "Change parameter"
    cls = DeepParamCommand if deep else ChangeParamCommand
    cmd = cls(node, param_id, old_val, new_val, description)
    stack = undo_stack_for(node)
    if stack is not None:
        stack.push(cmd)
    else:
        cmd.redo()
    return True


def push_params(node, changes, description):
    """Several params as one undo step. `changes` is [(param_id, old, new, deep)]."""
    changes = [c for c in changes if not _values_equal(c[1], c[2])]
    if node is None or not changes:
        return False
    stack = undo_stack_for(node)
    if stack is not None and len(changes) > 1:
        stack.beginMacro(description)
    try:
        for pid, old, new, deep in changes:
            push_param(node, pid, old, new, description, deep)
    finally:
        if stack is not None and len(changes) > 1:
            stack.endMacro()
    return True


def layers_of(node, pid="mask_layers"):
    """A deep copy of the node's mask layers, safe to edit and push."""
    return copy.deepcopy(getattr(node, "params", {}).get(pid) or [])


def push_layers(node, new_layers, description, pid="mask_layers", active_layer_id=None):
    """Replace the node's mask layers (and optionally the active layer) as one undo step."""
    params = getattr(node, "params", {})
    changes = [(pid, params.get(pid) or [], new_layers, True)]
    if active_layer_id is not None:
        changes.append(("active_layer_id", params.get("active_layer_id"), active_layer_id, False))
    return push_params(node, changes, description)
