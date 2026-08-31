# Prompt scenarios — snake_none_stream

**date:** 2026-08-31T00:36:13+00:00  
**revision:** 63d26a3  
**prompt:** `c929f4e20f9d` from app.context.window.DEFAULT_SYSTEM_PROMPT, 4421 characters  
**model:** gemma-4-12b-it at https://grigoriy-v--assistant-llm-v2-server-serve.modal.run/v1  
**sampling:** temperature 0.0, max_tokens 4096  
**planning:** none  
**streaming:** on  

Tool expectations are the only automatic check, and they are about the shape of the turn, not the quality of the answer. Read the answers.

| scenario | shape | model | tools | tokens in/out | seconds | derived $ |
| --- | --- | --- | --- | --- | --- | --- |
| snake | ok | 3 | write_file, inspect_page | 13774/1305 | 37.0 | 0.0148 |

Derived GPU cost for the whole run, upper bound: $0.0148.

## snake

**Request:** Создай html с игрой змейка, Назови Снейк_Гейм, проверь что работает

**Expected tools:** write_file, inspect_page  
**Called:** write_file, inspect_page  
**Outcome:** answer_delivered

**Look for:** живой отказ: write_file приходит с чужими полями и без path. Смотреть на аргументы первого вызова после todo_write

```text
write_file Снейк_Гейм.html success 0ms
inspect_page Снейк_Гейм.html success 1187ms
```

```text
Я создал файл `Снейк_Гейм.html` с игрой «Змейка».

**Как играть:**
*   Используйте **стрелки на клавиатуре** для управления направлением движения.
*   Собирайте красные квадраты, чтобы увеличиваться в размере и набирать очки.
*   Игра закончится, если вы врежетесь в стену или в собственный хвост.

Я проверил работу игры через браузер: графическое окно инициализируется корректно, змейка отображается, и логика движения/столкновений активна.
```
