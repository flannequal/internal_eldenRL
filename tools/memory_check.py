import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eldenrl.memory_mngr import MemoryManager


def format_value(value) -> str:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    mem = MemoryManager("eldenring.exe")
    if not mem.attach():
        return 1
    mem.load_addresses(os.path.join("config", "addresses.yaml"))
    if not mem.config:
        return 1

    print(f"module base: {hex(mem.module_base)}\n")
    failures = 0

    print("static bases")
    for name, rva in mem.config.get("bases_static", {}).items():
        value = mem.read_longlong(mem.module_base + rva)
        status = "ok  " if value else "FAIL"
        failures += 0 if value else 1
        print(f"  [{status}] {name:<20} {hex(mem.module_base + rva)} -> {hex(value) if value else 'null'}")

    print("\npointer chains")
    chains = {**mem.config.get("pointers", {}), **mem.config.get("teleport", {})}
    for name in chains:
        addr, value = mem.read_pointer(name)
        ok = addr is not None and value is not None
        failures += 0 if ok else 1
        status = "ok  " if ok else "FAIL"
        detail = f"{hex(addr)} = {format_value(value)}" if ok else "unresolved"
        print(f"  [{status}] {name:<24} {detail}")

    print(f"\n{len(chains) + len(mem.config.get('bases_static', {})) - failures} resolved, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
