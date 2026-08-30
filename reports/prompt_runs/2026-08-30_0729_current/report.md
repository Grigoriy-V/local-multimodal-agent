# Prompt scenarios — current

**date:** 2026-08-30T07:29:09+00:00  
**revision:** 17a84b8  
**prompt:** `5c4cb811133f` from app.context.window.DEFAULT_SYSTEM_PROMPT, 4695 characters  
**model:** gemma-4-12b-it at https://grigoriy-v--assistant-llm-v2-server-serve.modal.run/v1  
**sampling:** temperature 0.0, max_tokens 4096  

Tool expectations are the only automatic check, and they are about the shape of the turn, not the quality of the answer. Read the answers.

| scenario | shape | model | tools | tokens in/out | seconds | derived $ |
| --- | --- | --- | --- | --- | --- | --- |
| chat | ok | 1 | none | 2629/74 | 4.2 | 0.0046 |
| capabilities | ok | 1 | none | 2617/203 | 4.9 | 0.0051 |
| note | ok | 3 | list_files, write_file | 7981/115 | 3.6 | 0.0047 |
| castle | off | 1 | none | 2618/1925 | 43.9 | 0.0171 |
| broken_page | off | 3 | list_files, read_file | 8052/226 | 6.1 | 0.0055 |

Derived GPU cost for the whole run, upper bound: $0.0370.

## chat

**Request:** Привет. В двух предложениях: чем отличается префиксный кеш от кеша ответов?

**Expected tools:** none  
**Called:** none  
**Outcome:** answer_delivered

**Look for:** один ход модели, ноль инструментов. Это антирегрессия по стоимости.

```text
Префиксный кеш сохраняет результаты вычисления начальных токенов (префиксов) общего запроса, позволяя не пересчитывать их при изменении только конца промпта. Кеш ответов (Response Cache) хранит готовый результат для полностью идентичного запроса, позволяя мгновенно вернуть ответ без участия модели.
```

## capabilities

**Request:** Что ты умеешь? Коротко.

**Expected tools:** none  
**Called:** none  
**Outcome:** answer_delivered

**Look for:** перечисляет только то, что действительно подключено, и не отрицает способность, которая у него есть

```text
Я — интеллектуальный помощник. Вот что я умею:

*   **Работа с текстом:** пишу статьи, код, письма, перевожу тексты и делаю краткие пересказы.
*   **Анализ данных:** читаю файлы (PDF, DOCX, TXT, CSV), анализирую документы и извлекаю из них информацию.
*   **Поиск в интернете:** ищу актуальную информацию, читаю веб-страницы и собираю данные из сети.
*   **Работа с файлами:** могу создавать, редактировать и просматривать файлы в вашем рабочем пространстве.
*   **Визуальный анализ:** могу «видеть» изображения и анализировать скриншоты веб-страниц.
*   **Память:** запоминаю важные факты о ваших предпочтениях для будущих диалогов.

Если у вас есть конкретная задача — просто скажите, и я приступлю!
```

## note

**Request:** Запиши в notes.txt три дела на завтра.

**Expected tools:** write_file  
**Called:** list_files, write_file  
**Outcome:** answer_delivered

**Look for:** простая запись не должна порождать проверочный проход

```text
list_files . success 0ms
write_file notes.txt success 0ms
```

```text
Я записал три дела в файл `notes.txt`:

1. Сделать зарядку утром.
2. Зайти в магазин за продуктами.
3. Подготовить отчет по проекту.
```

## castle

**Request:** Создай HTML с средневековым замком.

**Expected tools:** write_file, inspect_page  
**Called:** none  
**Outcome:** answer_delivered

**Look for:** сама регрессия: сделал ли он файл вместо кода в чате, осмотрел ли результат сам, спросил ли разрешения

```text
Для создания визуально интересного средневекового замка с помощью чистого HTML и CSS, я подготовил код, который использует современные возможности CSS (Flexbox, анимации и градиенты) для создания атмосферы.

Так как я не могу генерировать изображения, я создал **стилизованный замок из CSS-фигур**.

### Как это работает:
1.  **Башни**: Созданы с помощью `border-radius` и градиентов для объема.
2.  **Крыши**: Имеют конусообразную форму.
3.  **Окна**: Маленькие светящиеся прорези.
4.  **Анимация**: Добавлено легкое движение облаков и "мерцание" окон.

Скопируйте этот код и сохраните как `castle.html`:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Средневековый замок</title>
    <style>
        :root {
            --castle-color: #5d5d5d;
            --roof-color: #8b0000;
            --window-color: #ffd700;
            --sky-color: #1a2a6c;
        }

        body {
            margin: 0;
            padding: 0;
            background: linear-gradient(to bottom, var(--sky-color), #b21f1f);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: flex-end;
            overflow: hidden;
            font-family: 'Georgia', serif;
        }

        /* Облака */
        .cloud {
            position: absolute;
            background: white;
            width: 100px;
            height: 40px;
            border-radius: 20px;
            opacity: 0.8;
            animation: moveClouds 30s linear infinite;
        }
        .cloud::after, .cloud::before {
            content: '';
            position: absolute;
            background: white;
            border-radius: 20px;
        }
        .cloud::after { width: 50px; height: 50px; top: -20px; left: 10px; }
        .cloud::before { width: 40px; height: 40px; top: -10px; left: 40px; }

        @keyframes moveClouds {
            from { left: -150px; }
            to { left: 100%; }
        }

        /* Основная сцена */
        .scene {
            position: relative;
            width: 800px;
            height: 600px;
            margin-bottom: 50px;
        }

        /* Замок */
        .castle-body {
            position: absolute;
            bottom: 0;
            width: 100%;
            height: 300px;
            background: var(--castle-color);
            border-top: 5px solid #333;
        }

        /* Башни */
        .tower {
            position: absolute;
            bottom: 0;
            width: 120px;
            height: 400px;
            background: var(--castle-color);
            border: 2px solid #333;
        }

        .tower-left { left: 50px; }
        .tower-right { right: 50px; }
        .tower-center { 
            left: 340px; 
            width: 120px; 
            height: 500px; 
            background: #4a4a4a;
            z-index: 2;
        }

        /* Крыши башен */
        .roof {
            position: absolute;
            top: -100px;
            left: -10px;
            width: 140px;
            height: 120px;
            background: var(--roof-color);
            clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
        }

        .tower-left .roof { left: -10px; }
        .tower-right .roof { right: -10px; }
        .tower-center .roof { left: -10px; height: 150px; }

        /* Окна */
        .window {
            position: absolute;
            width: 20px;
            height: 30px;
            background: var(--window-color);
            box-shadow: 0 0 15px var(--window-color);
            animation: flicker 3s infinite;
        }

        @keyframes flicker {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* Размещение окон */
        .tower-left .window { top: 100px; left: 50px; }
        .tower-left .window:nth-child(2) { top: 180px; left: 50px; }
        .tower-right .window { top: 100px; left: 50px; }
        .tower-right .window:nth-child(2) { top: 180px; left: 50px; }
        .tower-center .window { top: 150px; left: 50px; }
        .tower-center .window:nth-child(2) { top: 250px; left: 50px; }
        .tower-center .window:nth-child(3) { top: 350px; left: 50px; }

        /* Ворота */
        .gate {
            position: absolute;
            bottom: 0;
            left: 340px;
            width: 120px;
            height: 100px;
            background: #222;
            border: 4px solid #333;
            border-radius: 50px 50px 0 0;
        }

        /* Земля */
        .ground {
            position: absolute;
            bottom: 0;
            width: 100%;
            height: 50px;
            background: #1a3d1a;
            z-index: 1;
        }

        h1 {
            position: absolute;
            top: 50px;
            color: white;
            text-shadow: 2px 2px 4px black;
            font-size: 3rem;
        }
    </style>
</head>
<body>

    <h1>Замок Короля</h1>

    <div class="cloud" style="top: 100px; animation-delay: 0s;"></div>
    <div class="cloud" style="top: 150px; animation-delay: 5s;"></div>
    <div class="cloud" style="top: 80px; animation-delay: 12s;"></div>

    <div class="scene">
        <div class="castle-body"></div>
        
        <div class="tower tower-left">
            <div class="roof"></div>
            <div class="window"></div>
            <div class="window"></div>
        </div>

        <div class="tower tower-right">
            <div class="roof"></div>
            <div class="window"></div>
            <div class="window"></div>
        </div>

        <div class="tower tower-center">
            <div class="roof"></div>
            <div class="window"></div>
            <div class="window"></div>
            <div class="window"></div>
        </div>

        <div class="gate"></div>
        
        <div class="ground"></div>
    </div>

</body>
</html>
```
```

## broken_page

**Request:** Посмотри price.html и скажи, что с ним не так.

**Expected tools:** inspect_page  
**Called:** list_files, read_file  
**Outcome:** answer_delivered

**Look for:** белый текст на белом фоне и опечатка в textContnet видны только тому, кто действительно открыл страницу

```text
list_files . success 0ms
read_file price.html success 0ms
```

```text
В файле `price.html` есть несколько ошибок:

1.  **Опечатка в JavaScript**: В строке `<script>` написано `textContnet` вместо `textContent`. Из-за этого скрипт не будет работать, и заголовок не изменится.
2.  **Проблема с контрастом (CSS)**: У класса `.price` задан белый цвет текста (`color:#fff`) на белом фоне (`background:#fff`). Текст будет невидимым.
3.  **Отсутствие структуры**: Документ не имеет тега `<body>`, хотя это стандарт для HTML5.

**Рекомендации по исправлению:**
*   Исправить `textContnet` на `textContent`.
*   Изменить цвет текста в `.price` (например, на черный `#000`).
*   Обернуть содержимое в `<body>`.
```
