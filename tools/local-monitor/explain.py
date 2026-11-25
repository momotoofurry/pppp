"""Local LLM explanation of an alert (report 35.108): Ollama on this computer, nothing leaves it.
The LLM never decides anything: the alert comes from rules.py; the LLM gets the alert, what the rule means, and a short
summary of the last seconds, and writes three short lines in Traditional Chinese. If Ollama is not running, the rule's
own meaning is used instead."""
import json
import urllib.request

URL = 'http://127.0.0.1:11434/api/generate'
MODEL = 'qwen3:4b-instruct-2507-q4_K_M'

SYSTEM = (
    '你是 EMG 控制輔助機械臂實驗的監看助手。系統：前臂 4 顆肌電感測器 → 板子（STM32）辨識手勢 → 電腦上的手臂控制程式'
    '（兩種模式：模式 1 在架子前方平面上下左右；停下就鎖定物體或架子；模式 2 前後；握拳夾、張開放）→ Kinova 手臂。'
    '安全機制：放鬆就停、心跳中斷 0.5 秒停（deadman）、追蹤誤差保護、工作區邊界。現場有一位協助者負責急停。\n'
    '規則：只根據下面給你的「警示」、「這條規則的意思」和「最近紀錄」回答，不要編造沒給的數字或原因；'
    '不可以說和「這條規則的意思」矛盾的話（警示出現就代表條件已經成立）；不要猜受試者的動作或感受；'
    '不確定就說「從紀錄看不出來」。不要建議修改程式。'
    '嚴重度 high：建議的第一句是「請協助者準備急停、受試者先放鬆」。嚴重度 warn 或 info：不要叫人急停，說明要留意什麼。\n'
    '用繁體中文，剛好三行，每行不超過 60 字：\n發生什麼：…\n可能原因：…\n建議：…')


def prompt(alert, context):
    return (SYSTEM + '\n\n嚴重度：' + alert['severity'] + '\n警示：' +
            json.dumps({k: alert[k] for k in ('rule', 'title', 'data')}, ensure_ascii=False)
            + '\n這條規則的意思（已經成立的事實）：' + alert['meaning'] + '\n最近紀錄：' + context + '\n')


def fallback(alert):
    return f'發生什麼：{alert["title"]}\n說明：{alert["meaning"]}\n（本地 AI 沒有回應，這是規則本身的說明）'


def explain(alert, context, model=MODEL, timeout=60):
    body = json.dumps({'model': model, 'prompt': prompt(alert, context), 'stream': False,
                       'options': {'temperature': 0.2, 'num_predict': 220}}).encode('utf-8')
    try:
        req = urllib.request.Request(URL, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = json.loads(r.read().decode('utf-8')).get('response', '').strip()
        return text or fallback(alert), True
    except Exception:  # noqa: BLE001  (no Ollama, timeout: the rule's text is enough)
        return fallback(alert), False
