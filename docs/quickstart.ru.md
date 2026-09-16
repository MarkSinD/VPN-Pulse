# Быстрый старт

> **Статус: устанавливаемая предварительная версия.** Установщик, CLI, цикл мониторинга и API
> работают на чистой Ubuntu 24.04; то, что они наблюдают, пока вымышлено — сборщики для настоящих
> серверов и пробники идут следующими инкрементами. Эта страница честно говорит, что работает сегодня.

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

6. Посмотрите, как работает цикл мониторинга (по желанию).

   ```bash
   vpn-pulse run --demo --db demo.sqlite3
   ```

   Цикл собирает данные из «сценарного мира» (10 минут всё штатно, 5 — проблема в мобильной
   сети, 10 — один сервер недоступен, 15 — восстановление, и снова по кругу), оценивает, пишет
   снимки, переходы и события в `demo.sqlite3` и печатает то, что отправил бы бот:
   `[group] 🔴 Сервер 2: подключение не проходит — проверка подтвердила сбой` один раз и
   `[group] 🟢 Сервер 2: снова работает` при восстановлении. Запустите во втором терминале
   `python -m vpnpulse.dev --sqlite demo.sqlite3`, чтобы смотреть ту же базу в Mini App. `--once`
   делает один проход; `--config config.yaml` без `--demo` — настоящий цикл (отчёты пробников
   приходят через API, сборщики серверов — следующий инкремент). Ctrl+C останавливает; после
   перезапуска ничего не отправляется повторно.

7. Попробуйте командную строку администратора (по желанию).

   ```bash
   vpn-pulse init --dir ./my-install --language ru
   export VPN_PULSE_CONFIG=./my-install/config.yaml
   vpn-pulse server add --id my-vpn --type awg-host --name-ru "Мой сервер" --name-en "My server" --country NL
   vpn-pulse probe enroll pc
   vpn-pulse note set "Вечером работы" --expires 23:00
   vpn-pulse doctor
   ```

   `init` пишет `config.yaml`, создаёт базу и каталог секретов `0700` (ключи
   `--telegram-token-stdin --group-chat-id …` сохраняют токен бота файлом `0600`; он никогда не
   печатается). `doctor` даёт один следующий шаг на находку — те же тексты, что на экране
   администратора, — и завершает с кодом `0/1/2` (всё в порядке / предупреждения / ошибки). Все
   команды принимают `--config`, `--db` и `--lang` до или после глагола.

## Установка на сервер (Ubuntu 24.04)

```bash
./install.sh preflight                 # проверки без изменений: python 3.12 + venv, диск, systemd, caddy
./install.sh demo                      # без root: Mini App + API на вымышленных данных, http://127.0.0.1:8765/app/mvp.html
sudo ./install.sh install --demo-data  # системный пользователь vpn-pulse, /opt/vpn-pulse/releases/<id> со своим venv,
                                       # /etc/vpn-pulse/config.yaml + секреты (0700/0600), /var/lib/vpn-pulse,
                                       # юниты vpn-pulse-api + vpn-pulse-run, сниппет Caddy, doctor
sudo vpn-pulse doctor                  # обёртка запускает CLI от имени служебного пользователя
sudo ./install.sh upgrade              # из более нового checkout: копия базы, миграции, переключение, рестарт, doctor — при сбое откат
sudo ./install.sh rollback             # вернуть предыдущий релиз
sudo ./install.sh uninstall            # юниты и приложение; данные и секреты остаются (--purge удаляет)
```

Без `--yes` установка спрашивает язык, таймзону, домен Mini App (для сниппета Caddy), ссылку на
администратора, id группы и — скрытым вводом — токен бота; с флагами не спрашивает ничего
(`--language ru --timezone Europe/Riga --domain monitor.example.org --group-chat-id …
--telegram-token-stdin`). `--demo-data` заводит три вымышленных сервера и держит их в движении
(`vpn-pulse run --demo`), чтобы свежей установке было что показать; `vpn-pulse demo clear` убирает
их, когда появятся настоящие. Все изменяющие команды принимают `--dry-run`.

Вся последовательность — чистая установка, `doctor` OK, повторная установка без изменений,
обновление с резервной копией, откат, удаление с сохранением данных — это `scripts/install_check.sh`;
она идёт в CI на чистой Ubuntu 24.04 (с systemd), а локально — в контейнере:
`scripts/install_check.sh --docker`. Проектные заметки: [operations/doctor.md](operations/doctor.md),
[connect-server.md](connect-server.md).
