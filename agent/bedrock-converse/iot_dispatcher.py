"""IoT Dispatcher — thin routing layer for hardware commands.

Routes commands through the active HardwareProfile's send_command callable,
wrapping calls in error handling so no unhandled exceptions propagate.
"""

from hardware_profile import HardwareProfile


def dispatch_command(profile: HardwareProfile, tool_name: str, tool_input: dict) -> dict:
    """Route a command through the profile's send_command function.

    Delegates to ``profile.send_command(tool_name, tool_input)`` and returns
    the result directly on success.  On any exception, returns an error dict
    rather than propagating — satisfying Requirement 8.4 (no unhandled
    exceptions).

    Args:
        profile: The active robot's HardwareProfile.
        tool_name: Name of the tool/action to invoke.
        tool_input: Parameters dict for the tool.

    Returns:
        The dict returned by the profile's send_command, or an error dict
        ``{"status": "error", "action": tool_name, "message": ...}`` on failure.
    """
    try:
        return profile.send_command(tool_name, tool_input)
    except Exception as e:
        return {"status": "error", "action": tool_name, "message": str(e)}
