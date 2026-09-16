/*
 * GC-H743 最小可运行固件 —— LED1(PE7) 心跳 + USART1(PA9) 文本输出。
 *
 * 定位：这是 STM32 路线的**冒烟用例**，不是产品代码。它只验证四件事：
 *   1. 板级链接脚本能让 startup + HAL + 用户代码链成一个可烧录的镜像
 *   2. 时钟初始化在 HSI 64 MHz 上跑得通（480 MHz 的 PLL 树另案）
 *   3. HAL 的 SysTick 时基正常（心跳周期可测）
 *   4. USART1 能从 PA9 输出可读文本，供 S5 回读
 *
 * 硬件事实（board.yaml / 原理图）：
 *   LED1 = PE7，高电平点亮
 *   调试串口 = USART1，PA9(TX) / PA10(RX) → CH340N → miniUSB
 *
 * 刻意不用 printf：newlib-nano 的 printf 会牵进 _write/_sbrk 一整套 syscall，
 * 首版把变量压到最少。文本格式化用本文件里的极简整数转十进制。
 */

#include "stm32h7xx_hal.h"

UART_HandleTypeDef huart1;

static void SystemClock_Config(void);
static void Error_Handler(void);
static void uart_write(const char *s);
static void uart_write_u32(uint32_t v);
static uint32_t cstr_len(const char *s);

int main(void)
{
  HAL_Init();

  /* HSI 64 MHz。本板 HSE 是 25 MHz，480 MHz 的 PLL 树（HSE→PLL1→VOS0）
     留待 clock 支持文件落地；首版先跑通链路。 */
  SystemClock_Config();

  __HAL_RCC_GPIOE_CLK_ENABLE();

  GPIO_InitTypeDef led = {0};
  led.Pin   = GPIO_PIN_7;          /* LED1 on GC-H743 */
  led.Mode  = GPIO_MODE_OUTPUT_PP;
  led.Pull  = GPIO_NOPULL;
  led.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOE, &led);

  uart_write("GC-H743 boot\r\n");
  uart_write("SYSCLK=");
  uart_write_u32(SystemCoreClock);
  uart_write(" Hz  HCLK=");
  uart_write_u32(HAL_RCC_GetHCLKFreq());
  uart_write(" Hz\r\n");

  uint32_t tick = 0;
  while (1)
  {
    HAL_GPIO_TogglePin(GPIOE, GPIO_PIN_7);
    uart_write("HEARTBEAT tick=");
    uart_write_u32(tick++);
    uart_write(" uptime_ms=");
    uart_write_u32(HAL_GetTick());
    uart_write("\r\n");
    HAL_Delay(1000);
  }
}

static void SystemClock_Config(void)
{
  /* H743 上电默认是 LDO 供电 + VOS1；显式写一遍，避免依赖复位默认值。 */
  HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  RCC_OscInitTypeDef osc = {0};
  osc.OscillatorType      = RCC_OSCILLATORTYPE_HSI;
  osc.HSIState            = RCC_HSI_ON;
  osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  osc.PLL.PLLState        = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&osc) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitTypeDef clk = {0};
  clk.ClockType      = RCC_CLOCKTYPE_HCLK   | RCC_CLOCKTYPE_SYSCLK |
                       RCC_CLOCKTYPE_PCLK1  | RCC_CLOCKTYPE_PCLK2  |
                       RCC_CLOCKTYPE_D3PCLK1;
  clk.SYSCLKSource   = RCC_SYSCLKSOURCE_HSI;
  clk.AHBCLKDivider  = RCC_SYSCLK_DIV1;
  clk.APB1CLKDivider = RCC_HCLK_DIV1;
  clk.APB2CLKDivider = RCC_HCLK_DIV1;
  clk.APB3CLKDivider = RCC_HCLK_DIV1;
  clk.APB4CLKDivider = RCC_HCLK_DIV1;
  /* 64 MHz 用不到这么多等待周期；多给不误事，少给会静默取到错数据。 */
  if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* HAL_UART_Init 调用的弱符号 —— 在这里配 PA9/PA10 的复用功能。 */
void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
  if (huart->Instance != USART1)
  {
    return;
  }

  __HAL_RCC_USART1_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();

  GPIO_InitTypeDef gpio = {0};
  gpio.Pin       = GPIO_PIN_9 | GPIO_PIN_10;   /* PA9 = TX, PA10 = RX */
  gpio.Mode      = GPIO_MODE_AF_PP;
  gpio.Pull      = GPIO_NOPULL;
  gpio.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio.Alternate = GPIO_AF7_USART1;
  HAL_GPIO_Init(GPIOA, &gpio);
}

/* HAL 的时基回调 —— 不定义它 HAL_Delay 会永远卡住。 */
void SysTick_Handler(void)
{
  HAL_IncTick();
}

static void uart_write(const char *s)
{
  if (huart1.Instance == NULL)
  {
    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 115200;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    huart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
    if (HAL_UART_Init(&huart1) != HAL_OK)
    {
      Error_Handler();
    }
  }
  HAL_UART_Transmit(&huart1, (uint8_t *)s, (uint16_t)cstr_len(s), 1000);
}

static uint32_t cstr_len(const char *s)
{
  uint32_t n = 0;
  while (s[n] != '\0')
  {
    n++;
  }
  return n;
}

static void uart_write_u32(uint32_t v)
{
  char buf[11];
  int i = 10;
  buf[i] = '\0';
  if (v == 0)
  {
    buf[--i] = '0';
  }
  while (v > 0 && i > 0)
  {
    buf[--i] = (char)('0' + (v % 10));
    v /= 10;
  }
  uart_write(&buf[i]);
}

static void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
