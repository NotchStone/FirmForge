#!/usr/bin/env python3
"""Generate test code files for R08-R50"""
import json, os

reqs = json.load(open("docs/test_benchmark/NL_REQUIREMENTS.json"))["requirements"]

for req in reqs:
    rid = req["id"]
    rn = int(rid[1:])
    if rn <= 7:
        continue
    
    cat = req["category"]
    txt = req["text"]
    
    # Category-based templates
    if cat == "GPIO":
        reg = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);}void loop(){PORTB^=(1<<7);Serial.println("TOGGLE");delay(500);}'
        ino = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);}void loop(){digitalWrite(13,!digitalRead(13));Serial.println("TOGGLE");delay(500);}'
    elif cat == "USART":
        baud = 9600
        if "115200" in txt: baud = 115200
        elif "38400" in txt: baud = 38400
        elif "57600" in txt: baud = 57600
        reg = f'#include <Arduino.h>\nvoid setup(){{Serial.begin({baud});Serial.println("START");}}void loop(){{Serial.println("USART_OK");delay(1000);}}'
        ino = reg
    elif cat == "ADC":
        ch = 0
        if "CH1" in rid or "通道 1" in txt: ch = 1
        elif "CH2" in rid or "通道 2" in txt: ch = 2
        elif "CH3" in rid or "通道 3" in txt: ch = 3
        elif "CH4" in rid or "通道 4" in txt: ch = 4
        elif "CH5" in rid or "通道 5" in txt: ch = 5
        reg = f'#include <Arduino.h>\nvoid setup(){{Serial.begin(9600);Serial.println("START");}}void loop(){{int v=analogRead(A{ch});Serial.print("ADC=\");Serial.println(v);delay(1000);}}'
        ino = reg
    elif cat == "Timer":
        reg = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);TCCR1A=0;TCCR1B=(1<<WGM12)|(1<<CS12)|(1<<CS10);OCR1A=15624;TIMSK1=(1<<OCIE1A);}void loop(){if(TCNT1>=OCR1A){TCNT1=0;PORTB^=(1<<7);Serial.println("TICK");}}'
        ino = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);TCCR1A=0;TCCR1B=(1<<WGM12)|(1<<CS12)|(1<<CS10);OCR1A=15624;TIMSK1=(1<<OCIE1A);}void loop(){if(TCNT1>=OCR1A){TCNT1=0;digitalWrite(13,!digitalRead(13));Serial.println("TICK");}}'
    elif cat == "EEPROM":
        reg = '#include <Arduino.h>\n#include <avr/eeprom.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");uint8_t v=eeprom_read_byte((uint8_t*)0);Serial.print("EEPROM[0]=");Serial.println(v);eeprom_write_byte((uint8_t*)0,v+1);}void loop(){delay(1000);}'
        ino = '#include <Arduino.h>\n#include <EEPROM.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");uint8_t v=EEPROM.read(0);Serial.print("EEPROM[0]=");Serial.println(v);EEPROM.write(0,v+1);}void loop(){delay(1000);}'
    elif cat == "Interrupt":
        reg = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);DDRD&=~(1<<0);PORTD|=(1<<0);EICRA=(1<<ISC01);EIMSK=(1<<INT0);sei();}void loop(){if(EIFR&(1<<INTF0)){EIFR|=(1<<INTF0);PORTB^=(1<<7);Serial.println("INT0_TRIGGERED");}}'
        ino = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);pinMode(2,INPUT_PULLUP);}void loop(){static int last=HIGH;int b=digitalRead(2);if(b==LOW&&last==HIGH){digitalWrite(13,!digitalRead(13));Serial.println("BUTTON");delay(200);}last=b;}'
    elif cat == "Watchdog":
        reg = '#include <Arduino.h>\n#include <avr/wdt.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);wdt_enable(WDTO_2S);}void loop(){wdt_reset();PORTB^=(1<<7);Serial.println("ALIVE");delay(1000);}'
        ino = '#include <Arduino.h>\n#include <avr/wdt.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);wdt_enable(WDTO_2S);}void loop(){wdt_reset();digitalWrite(13,!digitalRead(13));Serial.println("ALIVE");delay(1000);}'
    elif cat == "Sleep":
        reg = '#include <Arduino.h>\n#include <avr/sleep.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);PORTB|=(1<<7);delay(2000);PORTB&=~(1<<7);set_sleep_mode(SLEEP_MODE_IDLE);sleep_mode();}void loop(){Serial.println("WAKE");PORTB|=(1<<7);delay(500);PORTB&=~(1<<7);set_sleep_mode(SLEEP_MODE_IDLE);sleep_mode();}'
        ino = '#include <Arduino.h>\n#include <avr/sleep.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);digitalWrite(13,HIGH);delay(2000);digitalWrite(13,LOW);set_sleep_mode(SLEEP_MODE_IDLE);sleep_mode();}void loop(){Serial.println("WAKE");digitalWrite(13,HIGH);delay(500);digitalWrite(13,LOW);set_sleep_mode(SLEEP_MODE_IDLE);sleep_mode();}'
    elif cat == "SPI":
        reg = '#include <Arduino.h>\n#include <SPI.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");SPI.begin();}void loop(){uint8_t r=SPI.transfer(0xAA);Serial.print("SPI_RX=");Serial.println(r);delay(1000);}'
        ino = reg
    elif cat == "TWI":
        reg = '#include <Arduino.h>\n#include <Wire.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");Wire.begin();}void loop(){Wire.beginTransmission(0x50);Wire.write(0);Wire.endTransmission();Wire.requestFrom(0x50,1);if(Wire.available()){Serial.print("TWI_DATA=");Serial.println(Wire.read());}delay(2000);}'
        ino = reg
    elif cat == "System":
        reg = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");uint8_t r=MCUSR;MCUSR=0;if(r&(1<<PORF))Serial.println("Power-on");if(r&(1<<EXTRF))Serial.println("External");if(r&(1<<WDRF))Serial.println("Watchdog");}void loop(){delay(1000);}'
        ino = reg
    else:
        reg = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);}void loop(){PORTB^=(1<<7);Serial.println("TICK");delay(500);}'
        ino = '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);}void loop(){digitalWrite(13,!digitalRead(13));Serial.println("TICK");delay(500);}'
    
    os.makedirs(f"boards/arduino_mega/apps/test_reg/R{rid}", exist_ok=True)
    os.makedirs(f"boards/arduino_mega/apps/test_ino/R{rid}", exist_ok=True)
    with open(f"boards/arduino_mega/apps/test_reg/R{rid}/main.cpp", "w") as f:
        f.write(reg)
    with open(f"boards/arduino_mega/apps/test_ino/R{rid}/R{rid}.ino", "w") as f:
        f.write(ino)

print(f"Generated R08-R50 ({43} app pairs * 2 = 86 test files)")
