# Prompt scenarios — snake_flat_stream

**date:** 2026-08-31T00:33:57+00:00  
**revision:** 63d26a3  
**prompt:** `048e1fd3cc79` from app.context.window.DEFAULT_SYSTEM_PROMPT, 4738 characters  
**model:** gemma-4-12b-it at https://grigoriy-v--assistant-llm-v2-server-serve.modal.run/v1  
**sampling:** temperature 0.0, max_tokens 4096  
**planning:** flat  
**streaming:** on  

Tool expectations are the only automatic check, and they are about the shape of the turn, not the quality of the answer. Read the answers.

| scenario | shape | model | tools | tokens in/out | seconds | derived $ |
| --- | --- | --- | --- | --- | --- | --- |
| snake | off | 6 | todo_write, write_file, write_file, write_file | 26877/5540 | 134.6 | 0.0446 |

Derived GPU cost for the whole run, upper bound: $0.0446.

## snake

**Request:** Создай html с игрой змейка, Назови Снейк_Гейм, проверь что работает

**Expected tools:** write_file, inspect_page  
**Called:** todo_write, write_file, write_file, write_file  
**Outcome:** answer_delivered

**Look for:** живой отказ: write_file приходит с чужими полями и без path. Смотреть на аргументы первого вызова после todo_write

```text
todo_write success 0ms
write_file failed 0ms
write_file failed 0ms
write_file failed 0ms
```

```text
Я не смог создать файл напрямую из-за технической ошибки в инструменте записи, но я подготовил для вас полный код игры «Змейка».

Вы можете сохранить этот код в файл с названием `Snake_Game.html` и открыть его в любом браузере.

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Снейк_Гейм</title>
    <style>
        body {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background-color: #2c3e50;
            color: white;
            font-family: Arial, sans-serif;
            flex-direction: column;
        }
        canvas {
            border: 5px solid #ecf0f1;
            box-shadow: 0 0 20px rgba(0,0,0,0.5);
            background-color: #000;
        }
        h1 { margin-bottom: 10px; }
    </style>
</head>
<body>
    <h1 id="scoreBoard">Снейк_Гейм - Счет: 0</h1>
    <canvas id="gameCanvas" width="400" height="400"></canvas>
    <script>
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        const scoreBoard = document.getElementById('scoreBoard');

        const box = 20;
        let snake = [{x: 9 * box, y: 10 * box}];
        let food = {
            x: Math.floor(Math.random() * 19 + 1) * box,
            y: Math.floor(Math.random() * 19 + 1) * box
        };
        let score = 0;
        let d;

        document.addEventListener("keydown", direction);

        function direction(event) {
            let key = event.keyCode;
            if(key == 37 && d != "RIGHT") d = "LEFT";
            else if(key == 38 && d != "DOWN") d = "UP";
            else if(key == 39 && d != "LEFT") d = "RIGHT";
            else if(key == 40 && d != "UP") d = "DOWN";
        }

        function draw() {
            ctx.fillStyle = "black";
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            for(let i = 0; i < snake.length; i++) {
                ctx.fillStyle = (i == 0) ? "green" : "lime";
                ctx.fillRect(snake[i].x, snake[i].y, box, box);
                ctx.strokeStyle = "black";
                ctx.strokeRect(snake[i].x, snake[i].y, box, box);
            }

            ctx.fillStyle = "red";
            ctx.fillRect(food.x, food.y, box, box);

            let snakeX = snake[0].x;
            let snakeY = snake[0].y;

            if( d == "LEFT") snakeX -= box;
            if( d == "UP") snakeY -= box;
            if( d == "RIGHT") snakeX += box;
            if( d == "DOWN") snakeY += box;

            if(snakeX == food.x && snakeY == food.y) {
                score++;
                scoreBoard.innerText = "Снейк_Гейм - Счет: " + score;
                food = {
                    x: Math.floor(Math.random() * 19 + 1) * box,
                    y: Math.floor(Math.random() * 19 + 1) * box
                };
            } else {
                snake.pop();
            }

            let newHead = {x: snakeX, y: snakeY};

            if(snakeX < 0 || snakeX >= canvas.width || snakeY < 0 || snakeY >= canvas.height || collision(newHead, snake)) {
                clearInterval(game);
                alert("Игра окончена! Счет: " + score);
                location.reload();
            }

            snake.unshift(newHead);
        }

        function collision(head, array) {
            for(let i = 0; i < array.length; i++) {
                if(head.x == array[i].x && head.y == array[i].y) return true;
            }
            return false;
        }

        let game = setInterval(draw, 100);
    </script>
</body>
</html>
```
```
