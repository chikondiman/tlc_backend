def render_shipped_email(display_order: str, tracking: str | None, carrier: str | None):
    """
    NOTE: This function is currently unused. main.py uses render_status_email() instead.
    Kept for backwards compatibility. display_order should be "D-###" format, never a UUID.
    """
    tracking_line = ""
    if tracking:
        tracking_line = f"<p><b>Tracking:</b> {carrier or ''} {tracking}</p>"

    return f"""
      <div style="font-family: Arial, sans-serif;">
        <h2>Your order has shipped</h2>
        <p>Order Number: <b>{display_order}</b></p>
        {tracking_line}
        <p>Thanks for supporting Discipline.</p>
      </div>
    """
