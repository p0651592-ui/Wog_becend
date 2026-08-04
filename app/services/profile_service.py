from datetime import datetime


def format_profile(stats: dict) -> str:
    return (
        f"📊 Игрок {stats.get('username', 'noname')} 📊\n\n"
        f"💎 Баланс: {stats.get('balance', 0)} WC\n"
        f"⭐ Звёзды: {stats.get('stars', 0)}\n"
        f"🕓 Играет с {stats.get('registered', datetime.utcnow().strftime('%d.%m.%Y'))}\n\n"
        f"📈 Выиграно сегодня: {stats.get('today_win', 0)} WC\n"
        f"📉 Проиграно сегодня: {stats.get('today_loss', 0)} WC\n"
        f"💰 Всего наиграно: {stats.get('total_volume', 0)} WC\n"
        f"💸 Наибольший баланс: {stats.get('max_balance', 0)} WC\n"
        f"🔥 Макс. коэффициент: {stats.get('max_multiplier', 0)}\n"
        f"🎉 Макс. выигрыш: {stats.get('max_win', 0)} WC"
    )
