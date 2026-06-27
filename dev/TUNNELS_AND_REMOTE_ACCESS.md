# LES Remote Access and Tunnel Map

Обновлено: 2026-05-27

## Назначение

Документ описывает текущую схему аварийного доступа между Mac mini, MacBook Air, Lenovo Legion, VPS и iPhone/Termius.

Главный принцип: ZeroTier остается основной приватной сетью, VPS используется как публичная точка входа и bastion, а для нестабильного пути VPS -> Legion используется reverse tunnel через Mac mini.

## Узлы

| Узел | Роль | Адрес | SSH user | Ключ |
|---|---|---:|---|---|
| Mac mini `mlrag` | основной хост | `10.195.146.98` | `ovc` | `~/.ssh/id_ed25519` |
| MacBook Air | клиент/управление | `10.195.146.176` | `chernetchenko` | `~/.ssh/id_ed25519` |
| Lenovo Legion | Windows-клиент | `10.195.146.20` | `Oleg` | `~/.ssh/legion_key` |
| VPS `box-925292` | public bastion / Caddy | public `185.185.71.196`, ZT `10.195.146.136` | `root` | `~/.ssh/id_ed25519` |
| VPS restricted user | ограниченный bastion для iPhone | `185.185.71.196` | `iphone` | `iphone-bastion_ed25519` |

ZeroTier network:

```text
8d1c312afa249de4 / lrag
10.195.146.0/24
```

## SSH config на Mac mini

Активные алиасы в `~/.ssh/config`:

```sshconfig
Host zt-mini mini mlrag
  HostName 10.195.146.98
  User ovc
  IdentityFile ~/.ssh/id_ed25519

Host zt-macbook-air macbook-air macbook
  HostName 10.195.146.176
  User chernetchenko
  IdentityFile ~/.ssh/id_ed25519

Host zt-legion legion
  HostName 10.195.146.20
  User Oleg
  IdentityFile ~/.ssh/legion_key

Host zt-box box box-925292
  HostName 10.195.146.136
  User root
  IdentityFile ~/.ssh/id_ed25519
```

Проверки:

```bash
ssh zt-mini 'hostname; whoami'
ssh zt-macbook-air 'hostname; whoami'
ssh zt-legion 'hostname & whoami'
ssh zt-box 'hostname; whoami'
```

## Прямые ZeroTier-пути

### Mac mini -> MacBook

Работает напрямую:

```bash
ssh zt-macbook-air
```

### MacBook -> Mac mini

Работает напрямую, с MacBook:

```bash
ssh zt-mini
```

### Mac mini -> Legion

Работает напрямую:

```bash
ssh zt-legion
```

Фактическая проверка:

```text
DESKTOP-G0EBFRO
desktop-g0ebfro\oleg
direct-mac-to-legion-ok
```

Важно: исходная ошибка была не в ZeroTier, а в параметрах SSH:

- сначала использовался неправильный user `ovc`;
- правильный user на Windows: `Oleg`;
- рабочий ключ: `~/.ssh/legion_key`;
- Windows shell использует `&` как разделитель команд, а не `;`.

## Почему нужен reverse tunnel до Legion

Mac mini может заходить на Legion напрямую по ZeroTier.

Проблема в другом направлении:

```text
VPS -> Legion
```

Этот путь вел себя нестабильно:

```text
ping 10.195.146.20 с VPS: потери / timeout
nc 10.195.146.20 22 с VPS: No route to host / timeout
```

При этом:

```text
Mac mini -> Legion: OK
VPS -> Mac mini: OK
```

Практический вывод: вместо того чтобы полагаться на нестабильный маршрут VPS -> Legion внутри ZeroTier, Mac mini держит reverse tunnel на VPS. Тогда iPhone/Termius заходит на VPS, а VPS отдает локальный порт, который физически обслуживается Mac mini и уходит дальше в Legion.

Вероятные причины нестабильности VPS -> Legion:

- ZeroTier path между VPS и Windows-узлом не всегда строится сразу;
- Windows firewall/ZeroTier adapter может иначе обрабатывать входящие пакеты от VPS, чем от Mac mini;
- direct peer path VPS <-> Legion может просыпаться с задержкой или падать в relay/timeout;
- SSH-аутентификация на Windows дополнительно усложнена тем, что `Oleg` состоит в Administrators.

Последний пункт важен: для admin-пользователей Windows OpenSSH читает ключи из:

```text
C:\ProgramData\ssh\administrators_authorized_keys
```

а не только из:

```text
C:\Users\Oleg\.ssh\authorized_keys
```

Поэтому новый `iphone-bastion_ed25519` был добавлен в user-level `authorized_keys`, но Windows OpenSSH его не принял. Рабочий ключ для Legion остается `legion_key`.

## Reverse tunnel Mac mini -> VPS -> Legion

LaunchAgent:

```text
~/Library/LaunchAgents/me.ovc.legion-tunnel.plist
```

Команда внутри агента:

```bash
/usr/bin/ssh \
  -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:22020:10.195.146.20:22 \
  root@185.185.71.196
```

Смысл:

```text
VPS 127.0.0.1:22020 -> Mac mini reverse SSH tunnel -> Legion 10.195.146.20:22
```

Статус на Mac mini:

```bash
launchctl print gui/$(id -u)/me.ovc.legion-tunnel
```

Проверка на VPS:

```bash
ssh root@185.185.71.196 'ss -ltnp | grep 22020'
ssh root@185.185.71.196 'nc -vz -w 5 127.0.0.1 22020'
```

Проверка полного пути через VPS:

```bash
ssh \
  -i ~/.ssh/legion_key \
  -o IdentitiesOnly=yes \
  -o HostKeyAlias=10.195.146.20 \
  -o ProxyCommand='ssh root@185.185.71.196 -W 127.0.0.1:22020' \
  Oleg@legion-via-vps \
  'hostname & whoami & echo reverse-tunnel-ok'
```

Ожидаемый результат:

```text
DESKTOP-G0EBFRO
desktop-g0ebfro\oleg
reverse-tunnel-ok
```

## iPhone / Termius

Файлы для импорта на iPhone:

```text
~/Documents/LES_iPhone_Access/iphone-bastion_ed25519
~/Documents/LES_iPhone_Access/legion_key
~/Documents/LES_iPhone_Access/iphone-bastion-ssh-config.txt
```

### Termius через существующий root-доступ к VPS

Если в Termius уже есть профиль:

```text
root@185.185.71.196
```

то можно использовать его как tunnel host.

#### Mac mini

Port forwarding в Termius:

```text
Local: 127.0.0.1:22098
Remote: 10.195.146.98:22
```

SSH-профиль:

```text
Host: 127.0.0.1
Port: 22098
User: ovc
Key: iphone-bastion_ed25519
```

#### MacBook

Port forwarding:

```text
Local: 127.0.0.1:22176
Remote: 10.195.146.176:22
```

SSH-профиль:

```text
Host: 127.0.0.1
Port: 22176
User: chernetchenko
Key: iphone-bastion_ed25519
```

#### Legion

Port forwarding:

```text
Local: 127.0.0.1:22020
Remote: 127.0.0.1:22020
```

SSH-профиль:

```text
Host: 127.0.0.1
Port: 22020
User: Oleg
Key: legion_key
```

### Restricted VPS user `iphone`

На VPS создан пользователь:

```text
iphone
```

Его `authorized_keys` ограничен только port forwarding:

```text
permitopen="10.195.146.98:22"
permitopen="10.195.146.176:22"
permitopen="127.0.0.1:22020"
```

Это безопаснее root-профиля, но если Termius Free не дает удобный Jump Host, root-профиль с local forwarding остается рабочим быстрым вариантом.

## Caddy / публичный HTTPS

VPS также держит Caddy:

```text
80/tcp  -> Caddy HTTP / ACME HTTP-01
443/tcp -> Caddy HTTPS / ACME TLS-ALPN-01
443/udp -> HTTP/3, не обязателен для сертификата
```

Проверка:

```bash
ssh root@185.185.71.196 'ss -ltnp | grep -E ":(80|443)\s"'
curl -I http://les.ovc.me
curl -I https://les.ovc.me
curl -I https://speckle.ovc.me
```

Интерпретация:

```text
HTTP 308 на http://...       = Caddy доступен на 80 и редиректит в HTTPS
HTTP 200/302/401 на https:// = TLS и backend живы
HTTP 502 на https://         = TLS жив, backend за Caddy не отвечает
timeout/refused              = порт/firewall/DNS проблема
```

На момент фиксации:

```text
speckle.ovc.me -> HTTPS OK, backend отвечает
les.ovc.me     -> HTTPS OK, backend отвечает через П.А.У.К. reverse tunnel на Mac Mini;
                  внешний runtime smoke прошёл 12/12
les.ovc.me/vv  -> HTTPS OK, standalone CAD/BIM viewer отдается Caddy напрямую
                  из /var/www/vv на VPS, без регистрации и без LES auth
```

## Быстрый чек-лист аварийного доступа

### Mac mini

```bash
ssh zt-mini
```

### MacBook

```bash
ssh zt-macbook-air
```

### Legion напрямую с Mac mini

```bash
ssh zt-legion
```

### Legion через VPS reverse tunnel

```bash
ssh root@185.185.71.196 'nc -vz -w 5 127.0.0.1 22020'
```

### Перезапуск Legion reverse tunnel

```bash
launchctl kickstart -k gui/$(id -u)/me.ovc.legion-tunnel
```

### Отключение Legion reverse tunnel

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/me.ovc.legion-tunnel.plist
```

## Краткий ответ на вопрос про Mac -> Lenovo

Mac mini может напрямую зайти на Lenovo Legion по SSH внутри ZeroTier:

```bash
ssh zt-legion
```

Если кажется, что не может, почти наверняка причина одна из этих:

1. Legion offline/sleep.
2. Неверный user: нужен `Oleg`, не `ovc`.
3. Неверный ключ: нужен `~/.ssh/legion_key`.
4. Windows OpenSSH для admin-пользователя читает `C:\ProgramData\ssh\administrators_authorized_keys`.
5. Команды для Windows shell нужно разделять через `&`, не через `;`.

Reverse tunnel нужен не потому, что Mac mini не видит Legion, а потому что VPS не имеет стабильного прямого пути до Legion в ZeroTier.
