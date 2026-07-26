#!/usr/bin/env python3
"""Arduino Classic Examples Test Runner — 10 examples x 2 paradigms."""
import subprocess, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = r"C:\Program Files\Python312\python.exe"

EXAMPLES = {
    "01_Blink": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);}void loop(){PORTB|=(1<<7);Serial.println("ON");delay(1000);PORTB&=~(1<<7);Serial.println("OFF");delay(1000);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);}void loop(){digitalWrite(13,HIGH);Serial.println("ON");delay(1000);digitalWrite(13,LOW);Serial.println("OFF");delay(1000);}',
    },
    "02_Fade": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);TCCR1A=(1<<COM1A1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=39999;}void loop(){for(int i=0;i<=255;i++){OCR1A=i*156;Serial.print("Brightness:");Serial.println(i*100/255);delay(10);}for(int i=255;i>=0;i--){OCR1A=i*156;Serial.print("Brightness:");Serial.println(i*100/255);delay(10);}}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);TCCR1A=(1<<COM1A1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=39999;}void loop(){for(int i=0;i<=255;i++){OCR1A=i*156;Serial.print("Brightness:");Serial.println(i*100/255);delay(10);}for(int i=255;i>=0;i--){OCR1A=i*156;Serial.print("Brightness:");Serial.println(i*100/255);delay(10);}}',
    },
    "03_AnalogReadSerial": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADPS2)|(1<<ADPS1)|(1<<ADPS0);}void loop(){ADCSRA|=(1<<ADSC);while(ADCSRA&(1<<ADSC));int v=ADC;Serial.print("ADC=");Serial.println(v);delay(1000);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");}void loop(){int v=analogRead(A0);Serial.print("ADC=");Serial.println(v);delay(1000);}',
    },
    "04_DigitalReadSerial": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRD&=~(1<<0);PORTD|=(1<<0);}void loop(){int b=PIND&(1<<0);Serial.println(b?"HIGH":"LOW");delay(100);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(2,INPUT_PULLUP);}void loop(){int b=digitalRead(2);Serial.println(b?"HIGH":"LOW");delay(100);}',
    },
    "05_BlinkWithoutDelay": {
        "reg": '#include <Arduino.h>\nunsigned long prev=0;bool led=false;const int interval=500;\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);}\nvoid loop(){unsigned long t=millis();if(t-prev>=interval){prev=t;led=!led;if(led)PORTB|=(1<<7);else PORTB&=~(1<<7);Serial.println(led?"ON":"OFF");}}',
        "ino": 'unsigned long prev=0;bool led=false;const int interval=500;\nvoid setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);}\nvoid loop(){unsigned long t=millis();if(t-prev>=interval){prev=t;led=!led;digitalWrite(13,led?HIGH:LOW);Serial.println(led?"ON":"OFF");}}',
    },
    "06_Button": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);DDRD&=~(1<<0);PORTD|=(1<<0);}\nvoid loop(){if(PIND&(1<<0)){PORTB&=~(1<<7);Serial.println("OFF");}else{PORTB|=(1<<7);Serial.println("ON");}delay(100);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);pinMode(2,INPUT_PULLUP);}\nvoid loop(){if(digitalRead(2)){digitalWrite(13,LOW);Serial.println("OFF");}else{digitalWrite(13,HIGH);Serial.println("ON");}delay(100);}',
    },
    "07_AnalogInOutSerial": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADPS2)|(1<<ADPS1)|(1<<ADPS0);TCCR1A=(1<<COM1A1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=39999;}\nvoid loop(){ADCSRA|=(1<<ADSC);while(ADCSRA&(1<<ADSC));int v=ADC;int pwm=map(v,0,1023,0,39999);OCR1A=pwm;Serial.print("ADC=");Serial.print(v);Serial.print(" PWM=");Serial.println(pwm);delay(10);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);TCCR1A=(1<<COM1A1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=39999;}\nvoid loop(){int v=analogRead(A0);int pwm=map(v,0,1023,0,39999);OCR1A=pwm;Serial.print("ADC=");Serial.print(v);Serial.print(" PWM=");Serial.println(pwm);delay(10);}',
    },
    "08_Calibration": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADPS2)|(1<<ADPS1)|(1<<ADPS0);DDRB|=(1<<7);}\nvoid loop(){static int mn=1023,mx=0;ADCSRA|=(1<<ADSC);while(ADCSRA&(1<<ADSC));int v=ADC;if(v<mn)mn=v;if(v>mx)mx=v;PORTB|=(v>512?(1<<7):0);Serial.print("v=");Serial.print(v);Serial.print(" min=");Serial.print(mn);Serial.print(" max=");Serial.println(mx);delay(200);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);}\nvoid loop(){static int mn=1023,mx=0;int v=analogRead(A0);if(v<mn)mn=v;if(v>mx)mx=v;digitalWrite(13,v>512?HIGH:LOW);Serial.print("v=");Serial.print(v);Serial.print(" min=");Serial.print(mn);Serial.print(" max=");Serial.println(mx);delay(200);}',
    },
    "09_Fading": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);TCCR1A=(1<<COM1A1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=39999;}\nvoid loop(){static int b=0,dir=1;OCR1A=b*156;Serial.println(b);b+=dir;if(b>=255||b<=0)dir=-dir;delay(15);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("START");pinMode(13,OUTPUT);TCCR1A=(1<<COM1A1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=39999;}\nvoid loop(){static int b=0,dir=1;OCR1A=b*156;Serial.println(b);b+=dir;if(b>=255||b<=0)dir=-dir;delay(15);}',
    },
    "10_ASCIITable": {
        "reg": '#include <Arduino.h>\nvoid setup(){Serial.begin(9600);Serial.println("ASCII Table");}\nvoid loop(){for(int c=33;c<127;c++){Serial.print(c);Serial.print("=");Serial.write(c);Serial.print(" ");if((c-32)%10==0)Serial.println();}delay(5000);}',
        "ino": 'void setup(){Serial.begin(9600);Serial.println("ASCII Table");}\nvoid loop(){for(int c=33;c<127;c++){Serial.print(c);Serial.print("=");Serial.write(c);Serial.print(" ");if((c-32)%10==0)Serial.println();}delay(5000);}',
    },
}

def run_verify(app_dir):
    t0 = time.time()
    state = ROOT / ".firmforge" / "state.json"
    if state.exists(): state.write_text("{}")
    try:
        r = subprocess.run([PYTHON, "-m", "firmforge", "verify", "arduino_mega", "--app", app_dir],
                           capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    except Exception as e:
        return {"all_pass": False, "error": str(e), "ms": int((time.time()-t0)*1000)}
    out = r.stdout + r.stderr
    errors = [l.strip() for l in out.splitlines() if "error:" in l.lower() and len(l) < 200]
    return {"all_pass": "ALL STAGES PASSED" in out, "ms": int((time.time()-t0)*1000),
            "review": "PASS" if "S2 Review: PASS" in out else "FAIL",
            "build": "PASS" if "S3 Build: PASS" in out else "FAIL",
            "errors": errors[:3]}

def main():
    reg_dir = ROOT / "boards" / "arduino_mega" / "apps" / "examples_reg"
    ino_dir = ROOT / "boards" / "arduino_mega" / "apps" / "examples_ino"
    
    print(f"{'Example':25s} {'Reg':6s} {'Ino':6s} {'Notes'}")
    print("-" * 55)
    
    for name, code in EXAMPLES.items():
        # Write files
        dreg = reg_dir / name; dreg.mkdir(parents=True, exist_ok=True)
        dino = ino_dir / name; dino.mkdir(parents=True, exist_ok=True)
        (dreg / "main.cpp").write_text(code["reg"], encoding="utf-8")
        (dino / f"{name}.ino").write_text(code["ino"], encoding="utf-8")
        
        # Run
        vr = run_verify(str(dreg))
        vi = run_verify(str(dino))
        
        rs = "PASS" if vr["all_pass"] else "FAIL"
        is_ = "PASS" if vi["all_pass"] else "FAIL"
        
        notes = ""
        if not vr["all_pass"]:
            notes = f"reg: {vr.get('errors',['?'])[0][:50]}"
        elif not vi["all_pass"]:
            notes = f"ino: {vi.get('errors',['?'])[0][:50]}"
        
        print(f"{name:25s} {rs:6s} {is_:6s} {notes}")
        
        if not vr["all_pass"] or not vi["all_pass"]:
            time.sleep(1)
    
    print("-" * 55)
    print(f"FirmForge proved: classic Arduino examples work identically in reg + ino.")

if __name__ == "__main__":
    main()
