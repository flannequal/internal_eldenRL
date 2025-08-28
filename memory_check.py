import logging
from memory_manager import MemoryManager

def check_memory_addresses():
    """
    Attaches to the Elden Ring process and iterates through all configured
    addresses, logging whether each one can be successfully resolved.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    mem = MemoryManager("eldenring.exe")
    if not mem.attach():
        return
        
    mem.load_addresses("config/addresses.yaml")
    
    config = mem.config
    if not config:
        logging.error("Aborting memory check due to missing configuration.")
        return

    logging.info("--- Starting Memory Address Check ---")

    # 1. Check Static Bases (verify we can read the base pointers)
    logging.info("\n[Checking Static Bases...]")
    static_bases = config.get("bases_static", {})
    for name in static_bases:
        # This gets the address where the base pointer is stored (module_base + RVA)
        addr_of_pointer = mem.module_base + static_bases[name]
        # This reads the actual value of the pointer (e.g., the address of WorldChrMan)
        value = mem.read_longlong(addr_of_pointer)
        if value:
            logging.info(f"  [OK] Static Base '{name}' -> Pointer at {hex(addr_of_pointer)} | Value: {hex(value)}")
        else:
            logging.error(f"  [FAIL] Static Base '{name}' -> Pointer at {hex(addr_of_pointer)} | Value: NULL or Read Fail")

    # 2. Check All Pointer Chains (Pointers and Teleport)
    logging.info("\n[Checking All Pointer Chains...]")
    all_pointers = {**config.get("pointers", {}), **config.get("teleport", {})}
    
    for name in all_pointers:
        # The public read_pointer method uses the definitive resolver.
        addr, value = mem.read_pointer(name)
        if addr and value is not None:
            # Format the output value for better readability
            if isinstance(value, bytes):
                formatted_value = value.hex()
            elif isinstance(value, float):
                formatted_value = f"{value:.2f}"
            else:
                formatted_value = value
            logging.info(f"  [OK] Pointer '{name}' -> {hex(addr)} | Value: {formatted_value}")
        else:
            logging.error(f"  [FAIL] Pointer '{name}'")

    logging.info("\n--- Memory Address Check Complete ---")

if __name__ == "__main__":
    check_memory_addresses()
