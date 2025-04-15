# --- Start of File: utils/error_utils.py ---
import traceback # Standard library for accessing stack trace information
import logging
import html # Standard library for HTML escaping

logger = logging.getLogger(__name__)

def format_error(exception: Exception, include_traceback: bool = True, max_length: int = 3000) -> str:
    """
    Formats an exception object into a detailed string for logging or display.

    This function aims to provide a concise yet informative summary of an error,
    optionally including a snippet of the traceback to help pinpoint the source.

    Args:
        exception (Exception): The exception object caught in a try...except block.
        include_traceback (bool): If True, attempts to include the last few lines
                                  of the traceback in the output string. Defaults to True.
        max_length (int): The maximum desired length of the returned error string.
                          If the formatted string exceeds this, it will be truncated
                          with markers ("... [TRUNCATED] ..."). Defaults to 3000.

    Returns:
        str: A formatted string containing the error type, message, and optionally
             a traceback snippet, truncated if necessary.
    """
    try:
        # Get the type/class name of the exception (e.g., 'ValueError', 'RuntimeError').
        error_type = type(exception).__name__
        # Get the main error message associated with the exception.
        error_msg = str(exception)
        # Basic error information string.
        basic_info = f"{error_type}: {error_msg}"

        tb_string = "" # Initialize traceback string part
        if include_traceback:
            # Try to format the traceback associated with the exception.
            try:
                # `traceback.format_exception` provides a list of strings,
                # formatted similarly to how Python prints unhandled exceptions.
                # `limit=15` restricts the depth of the traceback shown.
                tb_lines = traceback.format_exception(
                    type(exception), exception, exception.__traceback__, limit=15
                )
                # Extract a relevant snippet. Getting the *last* few lines is often
                # useful as it shows where the error ultimately occurred in the call stack.
                # Adjust the number of lines (-10) as needed.
                tb_snippet = "\n".join(tb_lines[-10:]) # Get last 10 lines
                # Add the snippet to the output string.
                tb_string = f"\n--- Traceback Snippet ---\n{tb_snippet.strip()}"
            except Exception as tb_err:
                # If formatting the traceback itself fails, record that.
                logger.warning(f"Could not format traceback for error '{basic_info[:100]}...': {tb_err}")
                tb_string = f"\n(Traceback formatting failed: {tb_err})"

        # Combine the basic info and the traceback string.
        full_error = f"{basic_info}{tb_string}"

        # --- Truncate if necessary ---
        # Ensure the final string doesn't exceed the specified maximum length.
        if len(full_error) > max_length:
            # Calculate cutoff points to preserve the beginning and end of the message.
            ellipsis = "\n ... [TRUNCATED] ... \n"
            cutoff = max_length - len(ellipsis)
            # Ensure cutoff is positive before dividing
            if cutoff <= 0:
                full_error = full_error[:max_length] # Simple truncation if max_length is too small
            else:
                 half_cutoff = cutoff // 2
                 # Combine the start, ellipsis, and end parts.
                 full_error = f"{full_error[:half_cutoff]}{ellipsis}{full_error[-half_cutoff:]}"

        return full_error

    except Exception as fmt_err:
        # --- Fallback if formatting the error itself fails ---
        logger.error(f"CRITICAL: Failed to format the original error ({type(exception).__name__}) itself! Formatting error: {fmt_err}", exc_info=True)
        # Return a basic, truncated representation of the original error.
        return f"Error formatting exception: {str(exception)[:max_length]}"


def format_error_for_html(exception_obj) -> str:
    """
    Formats an error message specifically for safe display within HTML.
    It escapes potentially harmful characters to prevent XSS attacks.

    Args:
        exception_obj: The exception object.

    Returns:
        str: An HTML-safe, truncated error message string.
    """
    # Keep this simple for UI display: just type and message, escaped.
    try:
        error_type = type(exception_obj).__name__
        error_msg = str(exception_obj)
        # Use html.escape to convert characters like '<', '>', '&' to their HTML entities.
        safe_msg = html.escape(f"{error_type}: {error_msg}")
        # Limit length for UI sanity, avoid overly long error messages in the browser.
        return safe_msg[:1000] # Truncate to 1000 characters
    except Exception as e:
        # Fallback if formatting fails
        logger.warning(f"Could not format error for HTML display: {e}")
        return "An unexpected error occurred (unable to format details)."
# --- END OF FILE: utils/error_utils.py ---