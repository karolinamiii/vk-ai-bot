import json
import os
import re
import time
import requests
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType

VK_TOKEN = os.getenv("VK_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROUP_ID = int(os.getenv("GROUP_ID"))
MODEL_NAME = "openrouter/healer-alpha"

# бесплатный вариант:
# model_name = "openrouter/free"


MEMORY_FILE = "memory.json"
MAX_HISTORY = 12


def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


chat_memory = load_memory()


def cleanup_math(text):
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text)
    text = text.replace("\\dfrac", "")
    text = text.replace("\\frac", "")
    text = text.replace("{", "")
    text = text.replace("}", "")
    return text


def send_message(vk, peer_id, text):
    result = vk.messages.send(
        peer_id=peer_id,
        message=text[:4000],
        random_id=int(time.time() * 1000000)
    )
    print(f"[SEND] peer_id={peer_id}: {text[:120]}")
    return result


def get_best_photo(attachments):
    for att in attachments:
        if att["type"] == "photo":
            sizes = att["photo"]["sizes"]
            best = max(sizes, key=lambda s: s["width"] * s["height"])
            return best["url"]
    return None


def build_messages(user_id, text, image_url=None):
    history = chat_memory.get(str(user_id), [])

    messages = [{
        "role": "system",
        "content": (
            "Отвечай по-русски. "
            "Не используй LaTeX. "
            "Формулы пиши обычным текстом."
        )
    }]

    messages.extend(history)

    if image_url:
        content = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url}
        })
        messages.append({
            "role": "user",
            "content": content
        })
    else:
        messages.append({
            "role": "user",
            "content": text
        })

    return messages


def ask_openrouter(messages):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": MODEL_NAME,
        "messages": messages
    }

    r = requests.post(
        OPENROUTER_API_URL,
        headers=headers,
        json=data,
        timeout=120
    )

    print("[OPENROUTER STATUS]", r.status_code)
    print("[OPENROUTER BODY]", r.text[:500])

    if r.status_code != 200:
        raise Exception(f"OpenRouter error {r.status_code}: {r.text}")

    answer = r.json()["choices"][0]["message"]["content"]
    return cleanup_math(answer)


def save_dialog(user_id, user_text, assistant_text, image_url=None):
    history = chat_memory.get(str(user_id), [])

    if image_url:
        content = []
        if user_text:
            content.append({"type": "text", "text": user_text})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url}
        })
        history.append({
            "role": "user",
            "content": content
        })
    else:
        history.append({
            "role": "user",
            "content": user_text
        })

    history.append({
        "role": "assistant",
        "content": assistant_text
    })

    history = history[-MAX_HISTORY:]
    chat_memory[str(user_id)] = history
    save_memory(chat_memory)


def handle_vk_message(event, vk):
    message = event.object["message"]

    peer_id = message["peer_id"]
    from_id = message["from_id"]
    text = (message.get("text") or "").strip()
    attachments = message.get("attachments", [])

    print(f"[RECV] from_id={from_id}, peer_id={peer_id}, text={text}")

    try:
        send_message(vk, peer_id, "Сообщение получено, обрабатываю...")

        image_url = get_best_photo(attachments)
        messages = build_messages(from_id, text, image_url)
        answer = ask_openrouter(messages)
        save_dialog(from_id, text, answer, image_url)

        send_message(vk, peer_id, answer)

    except Exception as e:
        print("[ERROR]", repr(e))
        send_message(vk, peer_id, f"Ошибка: {e}")


def main():
    if not VK_TOKEN:
        print("Нет VK_TOKEN")
        return

    if not OPENROUTER_API_KEY:
        print("Нет OPENROUTER_API_KEY")
        return

    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()

    longpoll = VkBotLongPoll(vk_session, 149745263)

    print("Бот запущен")

    while True:
        try:
            for event in longpoll.listen():
                print("[EVENT]", event.type)

                if event.type == VkBotEventType.MESSAGE_NEW:
                    handle_vk_message(event, vk)

        except KeyboardInterrupt:
            print("Бот остановлен")
            break
        except Exception as e:
            print("Ошибка:", repr(e))
            time.sleep(2)


if __name__ == "__main__":
    main()