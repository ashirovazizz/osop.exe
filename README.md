# osop.exe

Переводчик с человеческого на ОСОП. Помогает преподавателям DH-центра ИТМО писать оценочные средства в РПД так, чтобы их не возвращали на доработку.

- **check** проверяет описание оценочного средства по правилам ОСОП и показывает вероятный комментарий эксперта. Работает в браузере, без ИИ, текст никуда не отправляется.
- **build** собирает описание ОС из полей формы: регламент, срок, формат, пример, таблица критериев с уровнями. Сам сверяет сумму баллов.
- **rules** — чек-листы из инструкции ОСОП-2026, неписаные правила, выведенные из реальных замечаний, и словарь «ОСОП пишет → что хотят».
- **feed** — общая лента замечаний экспертов. Из неё считается «топ претензий», а теги правил попадают в `check`.

## Состав

| Файл | Что это |
|---|---|
| `index.html` | всё приложение: одна страница, без сборки и зависимостей |
| `server.py` | сервер для своего хостинга: отдаёт страницу и API ленты (Python 3.8+, только стандартная библиотека) |
| `data/feed.seed.json` | стартовые 8 замечаний ОСОП (осень 2026); копируются в `data/feed.json` при первом запуске |
| `data/feed.json` | рабочая лента; создаётся сервером и в git не попадает |
| `apps-script/Code.gs` | API ленты поверх Google Таблицы, для GitHub Pages |

## Открытая ссылка без VPN: GitHub Pages + Google Таблица

Это самый простой вариант: бесплатно, без своего сервера.

**Сайт.** В репозитории: Settings → Pages → Build and deployment → Source: *Deploy from a branch*, ветка `main`, папка `/ (root)` → Save. Через минуту-две сайт будет доступен по адресу https://ashirovazizz.github.io/osop.exe/

**Лента.** Без настройки лента на Pages открывается только для чтения: показываются стартовые замечания из `data/feed.seed.json`. Чтобы коллеги могли добавлять замечания, подключите Google Таблицу:

1. Откройте таблицу с лентой (первая строка: `id | date | rpd | course | expert | round | comment | tags | fix | outcome | ts`).
2. Расширения → Apps Script, вставьте `apps-script/Code.gs`, сохраните.
3. Начать развёртывание → Новое развёртывание → «Веб-приложение»; запуск от имени «Меня», доступ «Все».
4. Скопируйте URL `https://script.google.com/macros/s/…/exec` и вставьте его в `index.html` в `const SHEET_API=""`.
5. Закоммитьте изменение, Pages обновится сам.

Писать в ленту сможет любой, у кого есть ссылка на сайт. Если кто-то начнёт мусорить, записи легко удалить прямо в таблице.

## Запуск локально

```bash
python3 server.py
```

Откройте http://127.0.0.1:8080.

Без сервера `index.html` тоже откроется (например, двойным кликом), но лента работать не будет. Проверка и сборка ОС работают в любом случае.

## Деплой на сервер

### 1. Код и systemd

```bash
sudo git clone https://github.com/ashirovazizz/osop.exe.git /opt/osop-exe
```

```bash
sudo useradd --system --home /opt/osop-exe osop && sudo chown -R osop:osop /opt/osop-exe
```

Файл `/etc/systemd/system/osop-exe.service`:

```ini
[Unit]
Description=osop.exe
After=network.target

[Service]
User=osop
WorkingDirectory=/opt/osop-exe
Environment=OSOP_HOST=127.0.0.1
Environment=OSOP_PORT=8080
ExecStart=/usr/bin/python3 /opt/osop-exe/server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now osop-exe
```

### 2. nginx с паролем

В `server.py` нет авторизации: любой, кто откроет сайт, сможет писать в ленту. Поэтому закройте его basic auth или держите во внутренней сети.

```bash
sudo htpasswd -c /etc/nginx/.osop-htpasswd dh
```

```nginx
server {
    server_name osop.example.ru;

    auth_basic "osop.exe";
    auth_basic_user_file /etc/nginx/.osop-htpasswd;

    client_max_body_size 128k;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

HTTPS удобнее всего настроить через certbot: `sudo certbot --nginx -d osop.example.ru`.

### 3. Обновление

```bash
cd /opt/osop-exe && sudo -u osop git pull && sudo systemctl restart osop-exe
```

Лента лежит в `data/feed.json`, `git pull` её не трогает. Для резервной копии достаточно копировать этот файл.

## API ленты

| Метод | Путь | Тело |
|---|---|---|
| `GET` | `/api/feed` | — |
| `POST` | `/api/feed` | `{date, rpd, course, expert, round, comment, tags, fix, outcome, ts}`, обязательно только `comment` |
| `PATCH` | `/api/feed/<id>` | `{fix, outcome}`, где `outcome` — `wait`, `ok` или `bad` |

Страница сама выбирает хранилище ленты по порядку: свой сервер (`/api/feed`) → Google Таблица (`SHEET_API`) → встроенная база claude.ai → стартовая лента `data/feed.seed.json` только для чтения.

## Как обновлять правила

Правила и их тексты лежат в `index.html`:

- `RULES` — список неписаных правил R1–R10 с источниками;
- `RX` и функция `analyze` — проверки для `check`;
- `TAGRX` — как текст замечания превращается в теги правил в ленте.

Новое правило: добавьте запись в `RULES`, регулярку в `TAGRX` и, если его можно проверить по тексту, проверку в `analyze`.
