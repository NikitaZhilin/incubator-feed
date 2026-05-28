# Отложено до финальной отладки: безопасность, доступы, production hardening

Этот документ фиксирует задачи, которые важны для публичного запуска, но не
блокируют текущую тестовую разработку функционала. На текущем этапе тестирует
администратор, поэтому приоритет у доменных сценариев: что записывается, как
считается и как это видно в боте, сайте и Mini App.

## 1. Авторизация и user scope

Отложено до финальной отладки:

- заменить общий `WEB_LINK_TOKEN` на персональные web-ключи;
- хранить web-ключи только в хешированном виде;
- привязать каждый web-ключ к конкретному Telegram user ID;
- добавить отзыв web-ключа;
- добавить срок действия ключа или ротацию;
- запретить обычному пользователю выбирать `user_id` через query/form;
- ввести единый current-user контекст:
  - `AdminPrincipal`;
  - `LinkUserPrincipal`;
  - `TelegramInitDataPrincipal`;
- оставить администратору возможность выбирать тестового пользователя только в
  явном admin-режиме.

До этого в тестовом режиме допустимо использовать текущий вход для администратора
через `WEB_ADMIN_TOKEN` или `WEB_LINK_TOKEN`, если URL не передается внешним
пользователям.

## 2. Telegram Mini App auth

Отложено:

- серверная валидация Telegram `initData`;
- проверка подписи по `BOT_TOKEN`;
- проверка возраста auth data через `USER_AUTH_MAX_AGE_SECONDS`;
- запрет логирования raw `initData`;
- выбор механизма сессии для HTML-форм:
  - либо `initData -> signed/httpOnly session cookie`;
  - либо отказ от HTML form submit в Mini App и переход на JS `fetch` с
    `X-Telegram-Init-Data`;
- тесты на валидный, невалидный и просроченный `initData`.

Важно: простые HTML-формы не умеют отправлять кастомный
`X-Telegram-Init-Data`. Поэтому перед полноценной Mini App нужно явно выбрать
модель сессии или JSON API.

## 3. Test login

Отложено:

- добавить `WEB_TEST_LOGIN_ENABLED`;
- разрешать test login только при `WEB_TEST_LOGIN_ENABLED=true`;
- в production требовать `WEB_TEST_LOGIN_ENABLED=false`;
- добавить проверку в production checklist.

На текущем этапе тестовый вход нужен только администратору.

## 4. Production guards

Отложено:

- `API_DOCS_ENABLED=false` для production;
- отключение FastAPI docs/openapi наружу;
- strict CORS, если появится cross-origin API;
- проверка `WEB_PUBLIC_URL`:
  - HTTPS;
  - без trailing slash;
  - без `/web` или `/miniapp` в base URL, если это будет выбранным правилом;
- отдельная команда production-check;
- проверка, что `WEB_ADMIN_TOKEN` никогда не попадает в Telegram-ссылки;
- проверка, что `WEB_LINK_TOKEN` не используется как admin token.

## 5. Telegram launch hardening

Отложено:

- `WebAppInfo` только для HTTPS URL;
- BotFather checklist;
- Bot API `setChatMenuButton`;
- fallback для HTTP/local;
- отдельная кнопка выбора `Открыть сайт` / `Открыть Mini App`;
- тесты keyboard/helper поведения для Mini App.

## 6. Наблюдаемость и приватность

Отложено:

- события:
  - `opened_from_telegram_init_data`;
  - `opened_with_web_login_token`;
  - `auth_failed`;
  - `api_error`;
  - `write_operation_failed`;
- запрет текстов пользовательских данных в analytics payload;
- агрегаты в админке без названий партий, кормов, заметок и хозяйств;
- отдельный аудит логов перед production.

## 7. Итоговый критерий возврата к этому документу

Вернуться к hardening после того, как тестово подтверждены основные доменные
сценарии:

- запись яиц;
- покупка на склад;
- расчет и создание замеса;
- создание и редактирование поголовья;
- создание и редактирование стада;
- назначение смеси стаду;
- настройки разделов и погоды;
- видимость изменений между Telegram-ботом, сайтом и Mini App.
