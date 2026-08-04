from app.services.profile_service import format_profile


async def profile_command(profile_data: dict) -> str:
    """Text response for /bal, /бал and profile button."""
    return format_profile(profile_data)
