# Быстрый старт

> **Статус: предварительная версия для разработчиков.** Установщика и CLI пока нет. Эта страница
> честно говорит, что работает сегодня, а что в планах, — чтобы вы не потратили вечер на команду,
> которой не существует.

## Что есть сегодня

- ядро бэкенда с тестами (вычислитель состояний, конфигурация, миграция SQLite, mock-first API);
- проверенные контракты (OpenAPI 3.1, JSON Schema, словари RU/EN);
- интерактивные прототипы всех экранов, включая ошибки и первый запуск.

## Требования

- Python 3.12 или новее;
- браузер для прототипов.

## Шаги

1. Клонируйте и установите в виртуальное окружение.

   ```bash
   git clone https://github.com/MarkSinD/VPN-Pulse.git
   cd VPN-Pulse
   python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

   Успех: `pip` завершился без ошибок.

2. Запустите тесты.

   ```bash
   python -m pytest
   ```

   Успех: все тесты зелёные. Они покрывают вычислитель (ноль пользователей ≠ отказ, два
   подтверждения, устаревшее → нет данных), аутентификацию, разделение ролей, allowlist
   аналитики и поля контракта, на которые опирается интерфейс.

3. Проверьте контракты.

   ```bash
   python scripts/validate_specs.py
   ```

   Успех: строка вида `specs OK: 18 API paths, 26 schemas, 288 i18n keys`.

4. Откройте прототипы.

   Откройте `docs/prototypes/mvp.html` в браузере. Тёмная пунктирная полоса сверху — showcase:
   переключите сценарий на `unavailable` или `clean_install`, роль на `admin`, тему и язык.
   `docs/prototypes/android.html` — сценарий пробника, `docs/prototypes/onboarding.html` —
   первый запуск.

5. Запустите dev-сервер (по желанию).

   ```bash
   python -m vpnpulse.dev --scenario degraded
   ```

   Он поднимает настоящий API на демо-сценариях (`http://127.0.0.1:8765/api/v1/`) и раздаёт
   прототипы на `/app/`. Ключ `--sqlite demo.sqlite3` при первом запуске записывает выбранный
   сценарий в настоящую базу и отдаёт его через боевую модель чтения. Сессия — `POST /api/v1/dev/session?role=member|admin`; к любому запросу
   можно добавить `?scenario=<id>` (любой сценарий, кроме `loading`), `?lang=ru|en` или
   `?delay_ms=<n>`. Список сценариев — `GET /api/v1/dev/scenarios`. Dev-маршруты не входят в
   контракт и не существуют в развёрнутом приложении.

## Планируемый путь установки

Когда выйдет установщик, путь будет таким (пока недоступно):

```text
./install.sh demo          # интерфейс на фикстурах, без токена Telegram
./install.sh preflight     # проверки окружения без изменений
sudo ./install.sh install  # мастер из семи шагов: окружение, приложение, конфиг, секреты, HTTPS, Telegram, doctor
vpn-pulse server add       # подключить сервер (awg-host | awg-docker | hiddify)
vpn-pulse probe enroll pc  # одноразовый код привязки пробника
vpn-pulse doctor           # сквозная диагностика
```

Прогресс — в [CHANGELOG.md](../CHANGELOG.md). Проект установщика:
[operations/doctor.md](operations/doctor.md) и [connect-server.md](connect-server.md).
