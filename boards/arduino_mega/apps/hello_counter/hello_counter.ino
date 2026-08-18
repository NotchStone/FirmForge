/* R04: 通过串口以 9600 波特率持续输出 Hello World，每秒一次，带递增计数器 */
#include <Arduino.h>

uint32_t counter = 0;

void setup() {
    Serial.begin(9600);
}

void loop() {
    Serial.print("Hello World #");
    Serial.println(counter);
    counter++;
    delay(1000);
}
