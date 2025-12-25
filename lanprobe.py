import socket
import time
import argparse
import sys
from threading import Event

VERSION = "1.0.0"
stop_event = Event()


def print_params(args):
    print("=== Параметры запуска ===")
    print(f"Режим: {'Сервер' if args.mode == 'server' else 'Клиент'}")
    print(f"Протокол: {args.type.upper()}")

    if args.mode == "server":
        print(f"Порт: {args.port}")
        print(f"Целевая скорость: {args.speed} Мбит/с")
        print(f"Размер пакета: {args.packet} байт")
        if args.type == "udp":
            print(
                f"Целевой адрес: {args.target if args.target else 'broadcast (255.255.255.255)'}"
            )
    else:  # client
        print(f"Хост: {args.host}")
        print(f"Порт: {args.port}")
        print(f"Время измерения: {args.time} секунд")

    print("========================\n")


def main():
    epilog_text = """
Примеры запуска:

  Сервер: UDP broadcast (по умолчанию)
    python lanprobe.py server --type udp --speed 100 --port 5000

  Сервер: UDP unicast на конкретный IP
    python lanprobe.py server --type udp --speed 100 --port 5000 --target 192.168.2.114

  Клиент: просто слушает (работает в обоих случаях)
    python lanprobe.py client --type udp --port 5000 --time 20
    """

    parser = argparse.ArgumentParser(
        description="Простой тест пропускной способности сети",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog_text,
    )
    parser.add_argument("--version", action="version", version=f"LANProbe {VERSION}")
    parser.add_argument(
        "mode", choices=["server", "client"], help="Режим: server или client"
    )
    parser.add_argument(
        "--type",
        choices=["tcp", "udp"],
        default="tcp",
        help="Тип протокола (tcp или udp, по умолчанию: tcp)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=10.0,
        help="Целевая скорость в Мбит/с (для сервера, по умолчанию: 10.0)",
    )
    parser.add_argument(
        "--time",
        type=float,
        default=10.0,
        help="Время измерения в секундах (для клиента, по умолчанию: 10.0)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Адрес хоста (для клиента, по умолчанию: 127.0.0.1)",
    )
    parser.add_argument(
        "--packet",
        type=int,
        default=1400,
        help="Размер пакета в байтах (для сервера, по умолчанию: 1400)",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Целевой IP для UDP (unicast). Если не указан — используется broadcast",
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Порт (по умолчанию: 5000)"
    )

    args = parser.parse_args()

    # Вывод версии при обычном запуске
    print(f"LANProbe version {VERSION}\n")

    print_params(args)

    try:
        if args.mode == "server":
            run_server(args)
        else:
            run_client(args)
    except KeyboardInterrupt:
        print("\n\nПолучен сигнал прерывания (Ctrl+C). Завершение работы.")
        stop_event.set()


def run_server(args):
    print("Сервер запущен. Ожидание клиентов... (Ctrl+C для остановки)\n")

    if args.type == "tcp":
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_sock.bind(("", args.port))
        listen_sock.listen(5)
    else:
        # UDP сокет
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if args.target is None:
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            print("UDP режим: broadcast (255.255.255.255)")
        else:
            print(f"UDP режим: unicast на {args.target}")

    try:
        while not stop_event.is_set():
            if args.type == "tcp":
                server_tcp_session(listen_sock, args)
            else:
                server_udp_session(listen_sock, args)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        listen_sock.close()
        print("Сервер остановлен.")


def server_tcp_session(listen_sock, args):
    print(f"Ожидание TCP-подключения на порту {args.port}...")

    listen_sock.settimeout(1.0)
    conn = None
    addr = None
    try:
        while not stop_event.is_set():
            try:
                conn, addr = listen_sock.accept()
                print(f"\nПодключён клиент: {addr}")
                break
            except socket.timeout:
                continue
            except OSError:
                return
    except KeyboardInterrupt:
        stop_event.set()
        return

    if conn is None:
        return

    conn.settimeout(None)

    bytes_per_sec = args.speed * 125000
    packet_size = args.packet
    interval = packet_size / bytes_per_sec if bytes_per_sec > 0 else 0
    data = b"0" * packet_size
    next_send_time = time.perf_counter()

    try:
        while not stop_event.is_set():
            now = time.perf_counter()
            if now < next_send_time:
                time.sleep(max(0, next_send_time - now))
            conn.sendall(data)
            next_send_time += interval
    except (BrokenPipeError, ConnectionResetError, OSError):
        print(f"Клиент {addr} отключился.")
    finally:
        conn.close()
        print("Готов к новому подключению.\n")


def server_udp_session(sock, args):
    if args.target:
        dest_addr = (args.target, args.port)
        addr_desc = args.target
    else:
        dest_addr = ("255.255.255.255", args.port)
        addr_desc = "broadcast (255.255.255.255)"

    print(
        f"Начинаем передачу UDP-пакетов на {addr_desc} со скоростью {args.speed} Мбит/с"
    )

    bytes_per_sec = args.speed * 125000
    packet_size = args.packet
    interval = packet_size / bytes_per_sec if bytes_per_sec > 0 else 0
    data = b"0" * packet_size
    next_send_time = time.perf_counter()

    try:
        while not stop_event.is_set():
            now = time.perf_counter()
            if now < next_send_time:
                time.sleep(max(0, next_send_time - now))

            sock.sendto(data, dest_addr)
            next_send_time += interval
    except OSError as e:
        if not stop_event.is_set():
            print(f"Ошибка отправки UDP: {e}")


# Клиент остаётся без изменений (как в предыдущей версии)
def run_client(args):
    if args.type == "tcp":
        client_tcp(args)
    else:
        client_udp(args)


def client_tcp(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Измерение начальной задержки подключения
    start_connect = time.perf_counter()
    sock.connect((args.host, args.port))
    connect_latency = (time.perf_counter() - start_connect) * 1000  # в мс

    print(f"Подключено к {args.host}:{args.port} (TCP)")
    print(f"Задержка подключения: {connect_latency:.1f} мс")

    # Теперь измеряем задержку до первого пакета данных
    sock.settimeout(5.0)  # защита от зависания
    start_first_packet = time.perf_counter()
    try:
        data = sock.recv(8192)
        if not data:
            print("Сервер сразу закрыл соединение.")
            return
        first_packet_latency = (time.perf_counter() - start_first_packet) * 1000
        print(f"Задержка до первого пакета: {first_packet_latency:.1f} мс\n")
    except socket.timeout:
        print("Таймаут ожидания первого пакета от сервера.")
        sock.close()
        return

    # Основной цикл приёма
    total_bytes = len(data)  # уже получили первый пакет
    start_time = time.time()
    last_report_time = start_time
    last_bytes = total_bytes

    try:
        while not stop_event.is_set():
            sock.settimeout(0.1)
            try:
                data = sock.recv(8192)
                if not data:
                    print("Сервер закрыл соединение.")
                    break
                total_bytes += len(data)

                now = time.time()
                if now - last_report_time >= 1.0:
                    delta_bytes = total_bytes - last_bytes
                    speed_mbps = (delta_bytes * 8) / (now - last_report_time) / 1e6
                    elapsed = now - start_time
                    print(
                        f"[{elapsed:6.1f}s] Текущая скорость: {speed_mbps:6.2f} Мбит/с "
                        f"(всего: {total_bytes / (1024*1024):.2f} МБ)"
                    )
                    last_bytes = total_bytes
                    last_report_time = now

                if now - start_time >= args.time:
                    break
            except socket.timeout:
                continue
    finally:
        final_time = time.time() - start_time
        if final_time > 0:
            avg_speed = (total_bytes * 8) / final_time / 1e6
            print(
                f"\nИтоговая средняя скорость: {avg_speed:.2f} Мбит/с "
                f"за {final_time:.1f} секунд ({total_bytes / (1024*1024):.2f} МБ)"
            )
        sock.close()


def client_udp(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", args.port))  # слушаем на всех интерфейсах, на указанном порту
    sock.settimeout(5.0)

    print(f"Ожидание UDP-трафика на порту {args.port}...")

    total_bytes = 0
    start_time = None
    last_report_time = None
    last_bytes = 0

    try:
        # Ждём первый пакет — измеряем задержку от старта клиента до первого пакета
        start_wait = time.perf_counter()
        data, server_addr = sock.recvfrom(8192)
        first_packet_latency = (time.perf_counter() - start_wait) * 1000

        print(f"Обнаружен трафик от {server_addr}")
        print(f"Задержка до первого пакета: {first_packet_latency:.1f} мс\n")

        total_bytes = len(data)
        start_time = time.time()
        last_report_time = start_time
        last_bytes = total_bytes

        sock.settimeout(1.0)  # дальше — с таймаутом для Ctrl+C

        while not stop_event.is_set():
            try:
                data, _ = sock.recvfrom(8192)
                total_bytes += len(data)

                now = time.time()
                if now - last_report_time >= 1.0:
                    delta_bytes = total_bytes - last_bytes
                    speed_mbps = (delta_bytes * 8) / (now - last_report_time) / 1e6
                    elapsed = now - start_time
                    print(
                        f"[{elapsed:6.1f}s] Текущая скорость: {speed_mbps:6.2f} Мбит/с "
                        f"(всего: {total_bytes / (1024*1024):.2f} МБ)"
                    )
                    last_bytes = total_bytes
                    last_report_time = now

                if now - start_time >= args.time:
                    break
            except socket.timeout:
                continue

    except socket.timeout:
        print("Таймаут: трафик не обнаружен за 5 секунд.")
    finally:
        if start_time is not None:
            final_time = time.time() - start_time
            if final_time > 0:
                avg_speed = (total_bytes * 8) / final_time / 1e6
                print(
                    f"\nИтоговая средняя скорость: {avg_speed:.2f} Мбит/с "
                    f"за {final_time:.1f} секунд ({total_bytes / (1024*1024):.2f} МБ)"
                )
        sock.close()


if __name__ == "__main__":
    main()
