import sys, yaml
sys.path.insert(0, '.')

from firmforge.providers.arduino.flash import ArduinoFlashProvider

board = yaml.safe_load(open('boards/arduino_328p/board.yaml', 'r', encoding='utf-8'))
f = ArduinoFlashProvider(board)
port = sys.argv[1] if len(sys.argv) > 1 else 'COM4'

print('avrdude:', f._toolchain.avrdude)
print('part:', f._mcu_part)
print('programmer:', f._resolve_programmer())
print('baud:', f._resolve_baud())

fr = f._run_avrdude('flash', 'boards/arduino_328p/apps/modbus_slave/firmware.hex', port)
print('FLASH:', 'OK' if fr.success else 'FAIL')
if fr.success:
    print('bytes_written:', fr.bytes_written)
    print('elapsed:', fr.elapsed_ms, 'ms')
else:
    print('STDERR:', (fr.stderr or '')[-600:])
