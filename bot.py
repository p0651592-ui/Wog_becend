from fastapi import FastAPI, Request
import requests

app = FastAPI()

# Ваши данные
TELEGRAM_TOKEN = "8804973603:AAHqWkyFQv8qW2ZZUHn7RSqVddqVCN6_vXs"
CHAT_ID = "-1004438070296"  # Например, "-100XXXXXXXXXX"

@app.post("/github-webhook")
async def github_webhook(request: Request):
    payload = await request.json()
    
    # Проверяем наличие коммитов (событие push)
    if "commits" in payload:
        repo_name = payload["repository"]["full_name"]
        branch = payload["ref"].split("/")[-1]
        pusher = payload["pusher"]["name"]
        
        # Собираем список коммитов
        commit_text = ""
        for commit in payload["commits"]:
            short_id = commit["id"][:7]
            commit_text += f"\n• [{short_id}] {commit['message']} — {commit['author']['name']}"
            
        message = (
            f"🚀 <b>Новый пуш в репозиторий!</b>\n\n"
            f"📦 <b>Репозиторий:</b> {repo_name}\n"
            f"🌿 <b>Ветка:</b> {branch}\n"
            f"👤 <b>Автор:</b> {pusher}\n"
            f"💬 <b>Коммиты:</b>{commit_text}"
        )
        
        # Отправка в Telegram
        url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })
        
    return {"status": "ok"}
