// ESP32 Rover + 5-servo Arm: the backend of the Manual tab on the laptop page (control.html).
//
// The ESP32 joins the same phone hotspot as the camera board (name and password in secrets.h, copy
// secrets.example.h), so the laptop, the camera and the arm are all on ONE network. It announces
// itself as still-arm.local and prints its address on the serial port. Open http://still-arm.local
// for the built-in page, or use the Manual tab of the laptop site, which talks to the same endpoints
// (see laptop/control.ts):
//   /drive?d=F&v=170   /servo?n=1&a=90   /armspeed?v=3   /home   /stop   /test   /state
//
// If the hotspot cannot be joined in 20 s, it makes its own network instead (ROVER_ARM, address 192.168.4.1,
// password ARM_AP_PASSWORD from secrets.h, or the public default 12345678 if you did not set one) so the arm
// can still be driven.
//
// Build with:  pio run -d firmware -e rover_arm -t upload
// (classic ESP32 pins below; the camera/planner firmware is main.cpp, env esp32s3)
//
// Library needed: "Adafruit PWM Servo Driver Library". WiFi, WebServer and ESPmDNS come with the board package.
//
// Servos on the PCA9685:
//   ch 0 = BASE   ch 1 = SHOULDER   ch 2 = ELBOW   ch 3 = WRIST   ch 4 = GRIPPER

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy firmware/secrets.example.h to firmware/secrets.h and fill in your Wi-Fi name and password."
#endif

// Fallback network, only used when the hotspot cannot be joined. Set ARM_AP_PASSWORD in secrets.h (at least
// 8 characters): the built-in default is public, because it is in the repository, so anyone who knows it
// could join the fallback network and drive the rover.
#ifdef ARM_AP_PASSWORD
static_assert(sizeof(ARM_AP_PASSWORD) >= 9, "ARM_AP_PASSWORD must be at least 8 characters");
const char* AP_PASS = ARM_AP_PASSWORD;
#else
const char* AP_PASS = "12345678";
#endif
const char* AP_SSID = "ROVER_ARM";
const char* HOST_NAME = "still-arm";
const unsigned long WIFI_JOIN_TIMEOUT_MS = 20000;

WebServer server(80);
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

// ---------- L298N pins ----------
const int ENA = 25;
const int IN1 = 26;
const int IN2 = 27;
const int IN3 = 13;
const int IN4 = 32;
const int ENB = 33;

// ---------- I2C pins (PCA9685) ----------
const int SDA_PIN = 21;
const int SCL_PIN = 22;

// ---------- PWM for wheel speed ----------
const int PWM_FREQ = 1000;
const int PWM_BITS = 8;

// =====================================================================
//  CORRECTION SWITCHES - fix direction problems here, no rewiring needed
// =====================================================================
// Press FORWARD on the page, then use this table:
//
//   What the rover does on FORWARD          Fix
//   -------------------------------------   --------------------------------
//   Goes straight forward                   nothing (check RIGHT next)
//   Spins to the RIGHT                      INVERT_RIGHT = true
//   Spins to the LEFT                       INVERT_LEFT  = true
//   Goes straight BACKWARD                  INVERT_LEFT = true AND INVERT_RIGHT = true
//
// Then press RIGHT:
//   Turns left instead of right             LEFT_MOTORS_ON_OUT3_OUT4 = true
//
// INVERT_LEFT / INVERT_RIGHT mean the real left / right side of the rover.
const bool INVERT_LEFT  = false;
const bool INVERT_RIGHT = true;     // matches your earlier fix (forward spun right)
const bool LEFT_MOTORS_ON_OUT3_OUT4 = false;

// Rover stops by itself if the page stops sending commands (finger lifted, WiFi lost)
const unsigned long DRIVE_TIMEOUT_MS = 400;

// ---------- Servos ----------
enum { BASE = 0, SHOULDER = 1, ELBOW = 2, WRIST = 3, GRIPPER = 4 };
const int NUM_SERVOS = 5;
const char* SERVO_NAME[5] = { "BASE", "SHOULDER", "ELBOW", "WRIST", "GRIPPER" };

// Pulse range in PCA9685 ticks (of 4096 at 50 Hz).
// If a servo buzzes at its end of travel, narrow this range a little.
const int SERVO_MIN_TICK = 150;   // about 0 degrees
const int SERVO_MAX_TICK = 600;   // about 180 degrees

// Safe angle limits for each joint. TUNE THESE on your real arm.
// These are also the ends of the sliders on the web page.
//                              BASE  SHOULDER ELBOW WRIST GRIPPER
const float MIN_ANGLE[5]  = {    0,     30,     20,    20,    30 };
const float MAX_ANGLE[5]  = {  180,    150,    160,   160,   110 };
const float HOME_ANGLE[5] = {   90,     90,     90,    90,    90 };

// If a slider moves its joint the WRONG way, set that joint to true.
// (Slider right should mean: base right, shoulder/elbow/wrist up, gripper open.)
// The slider and the limits above always stay in "slider angles".
//                                  BASE   SHOULDER ELBOW WRIST GRIPPER
const bool SERVO_INVERT[5] = {      false,  false,  false, false, false };

float angle[5];                 // where the servo is now
float target[5];                // where it is heading
float armStep = 1.8;            // max degrees per 20 ms tick (arm speed)
unsigned long lastTick = 0;

int driveSpeed = 170;           // 100..255
bool driving = false;
unsigned long lastDriveMs = 0;

// ---------- Web page ----------
const char PAGE[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Rover + Arm</title>
<style>
:root{--bg:#0e1124;--card:#1f2545;--a:#ffc93c;--b:#22d3ee;--r:#ff4b55;--g:#4ade80}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:#fff;font-family:system-ui,Arial,sans-serif;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
h1{font-size:18px;margin:0;padding:12px 14px;display:flex;align-items:center;gap:8px}
#dot{width:12px;height:12px;border-radius:50%;background:var(--r)}
.wrap{display:grid;gap:12px;padding:0 12px 16px;grid-template-columns:1fr}
@media (min-width:700px),(orientation:landscape){.wrap{grid-template-columns:1fr 1fr}}
.card{background:var(--card);border-radius:14px;padding:12px}
.card h2{margin:0 0 10px;font-size:15px;color:var(--a);letter-spacing:1px}
.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.pad button{height:68px;font-size:26px;border:0;border-radius:12px;background:#2d3560;color:#fff;touch-action:none}
.pad button.on{background:var(--a);color:#000}
.pad .stop{background:var(--r)}
.row{display:flex;align-items:center;gap:8px;margin:12px 0}
.row label{width:76px;font-weight:700;font-size:14px}
.row input{flex:1;height:38px;touch-action:pan-y}
.row span{width:38px;text-align:right;font-variant-numeric:tabular-nums}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.btns button{flex:1;padding:14px 8px;border:0;border-radius:10px;font-weight:700;font-size:14px;background:var(--b);color:#000}
.btns .red{background:var(--r);color:#fff}
.btns .grn{background:var(--g)}
</style></head><body>
<h1><span id="dot"></span>ROVER + ARM</h1>
<div class="wrap">
 <div class="card">
  <h2>DRIVE</h2>
  <div class="pad">
   <button data-d="Q">&#8598;</button><button data-d="F">&#8593;</button><button data-d="E">&#8599;</button>
   <button data-d="L">&#8592;</button><button data-d="S" class="stop">&#9632;</button><button data-d="R">&#8594;</button>
   <button data-d="Z">&#8601;</button><button data-d="B">&#8595;</button><button data-d="C">&#8600;</button>
  </div>
  <div class="row"><label>Speed</label><input id="spd" type="range" min="100" max="255" value="170"><span id="spdv">170</span></div>
 </div>
 <div class="card">
  <h2>ARM</h2>
  <div id="arm"></div>
  <div class="row"><label>Arm speed</label><input id="aspd" type="range" min="1" max="8" value="3"><span id="aspdv">3</span></div>
  <div class="btns">
   <button id="open" class="grn">Open grip</button>
   <button id="close" class="grn">Close grip</button>
   <button id="home">Arm home</button>
   <button id="test">Test arm</button>
  </div>
  <div class="btns"><button id="stopall" class="red">STOP ALL</button></div>
 </div>
</div>
<script>
const $=id=>document.getElementById(id);
const N=['Base','Shoulder','Elbow','Wrist','Gripper'];
const sl=[],vl=[],lastT=[0,0,0,0,0];
let drag=-1,spd=170;
function send(u){return fetch(u).catch(()=>{});}

// Drive pad: hold = keep sending every 120 ms, release = stop
document.querySelectorAll('[data-d]').forEach(b=>{
  let t=null;
  const go=()=>send('/drive?d='+b.dataset.d+'&v='+spd);
  b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('on');go();clearInterval(t);t=setInterval(go,120);});
  const end=e=>{b.classList.remove('on');if(t!==null){clearInterval(t);t=null;send('/drive?d=S');}};
  ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,end));
  b.addEventListener('contextmenu',e=>e.preventDefault());
});
$('spd').oninput=e=>{spd=+e.target.value;$('spdv').textContent=spd;};
$('aspd').oninput=e=>{$('aspdv').textContent=e.target.value;send('/armspeed?v='+e.target.value);};

// Arm sliders
function setServo(i,val){send('/servo?n='+(i+1)+'&a='+val);}
async function init(){
  const s=await (await fetch('/state')).json();
  N.forEach((n,i)=>{
    const r=document.createElement('div');r.className='row';
    r.innerHTML='<label>'+n+'</label><input type="range" min="'+s.min[i]+'" max="'+s.max[i]+'" value="'+s.a[i]+'"><span>'+s.a[i]+'</span>';
    const inp=r.children[1],v=r.children[2];
    sl.push(inp);vl.push(v);
    inp.addEventListener('pointerdown',()=>drag=i);
    ['pointerup','pointercancel'].forEach(ev=>inp.addEventListener(ev,()=>drag=-1));
    inp.addEventListener('input',()=>{v.textContent=inp.value;const t=Date.now();if(t-lastT[i]>60){lastT[i]=t;setServo(i,inp.value);}});
    inp.addEventListener('change',()=>setServo(i,inp.value));
    $('arm').appendChild(r);
  });
  poll();
}
async function poll(){
  try{
    const s=await (await fetch('/state')).json();
    $('dot').style.background='#4ade80';
    s.a.forEach((a,i)=>{if(drag!==i&&sl[i]){sl[i].value=a;vl[i].textContent=a;}});
  }catch(e){$('dot').style.background='#ff4b55';}
  setTimeout(poll,700);
}
$('open').onclick=()=>{sl[4].value=sl[4].max;vl[4].textContent=sl[4].max;setServo(4,sl[4].max);};
$('close').onclick=()=>{sl[4].value=sl[4].min;vl[4].textContent=sl[4].min;setServo(4,sl[4].min);};
$('home').onclick=()=>send('/home');
$('test').onclick=()=>send('/test');
$('stopall').onclick=()=>send('/stop');
init().catch(()=>{$('dot').style.background='#ff4b55';setTimeout(()=>location.reload(),1500);});
</script></body></html>
)rawliteral";

// ---------- PWM helper (works on Core 2.x and 3.x) ----------
void pwmSetup() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(ENA, PWM_FREQ, PWM_BITS);
  ledcAttach(ENB, PWM_FREQ, PWM_BITS);
#else
  ledcSetup(0, PWM_FREQ, PWM_BITS);
  ledcSetup(1, PWM_FREQ, PWM_BITS);
  ledcAttachPin(ENA, 0);
  ledcAttachPin(ENB, 1);
#endif
}

void pwmWrite(int pin, int duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  ledcWrite(pin == ENA ? 0 : 1, duty);
#endif
}

// ---------- Wheel control ----------
void setMotor(int en, int a, int b, int speed) {
  speed = constrain(speed, -255, 255);
  if (speed > 0) {
    digitalWrite(a, HIGH);
    digitalWrite(b, LOW);
  } else if (speed < 0) {
    digitalWrite(a, LOW);
    digitalWrite(b, HIGH);
  } else {
    digitalWrite(a, LOW);
    digitalWrite(b, LOW);
  }
  pwmWrite(en, abs(speed));
}

void drive(int left, int right) {
  if (INVERT_LEFT)  left  = -left;
  if (INVERT_RIGHT) right = -right;

  if (LEFT_MOTORS_ON_OUT3_OUT4) {
    setMotor(ENA, IN1, IN2, right);   // OUT1/OUT2 carry the right side
    setMotor(ENB, IN3, IN4, left);    // OUT3/OUT4 carry the left side
  } else {
    setMotor(ENA, IN1, IN2, left);    // OUT1/OUT2 carry the left side
    setMotor(ENB, IN3, IN4, right);   // OUT3/OUT4 carry the right side
  }
}

void driveCmd(char c) {
  int turn  = driveSpeed * 9 / 10;
  int inner = driveSpeed * 4 / 10;

  driving = (c != 'S');
  lastDriveMs = millis();

  switch (c) {
    case 'F': drive(driveSpeed, driveSpeed); break;
    case 'B': drive(-driveSpeed, -driveSpeed); break;
    case 'L': drive(-turn, turn); break;
    case 'R': drive(turn, -turn); break;
    case 'Q': drive(inner, driveSpeed); break;     // forward-left
    case 'E': drive(driveSpeed, inner); break;     // forward-right
    case 'Z': drive(-inner, -driveSpeed); break;   // reverse-left
    case 'C': drive(-driveSpeed, -inner); break;   // reverse-right
    default:  drive(0, 0); driving = false; break;
  }
}

// ---------- Servo control ----------
void writeServo(int ch, float deg) {
  deg = constrain(deg, 0, 180);
  if (SERVO_INVERT[ch]) deg = 180 - deg;
  int tick = map((int)(deg * 10), 0, 1800, SERVO_MIN_TICK, SERVO_MAX_TICK);
  pwm.setPWM(ch, 0, tick);
}

// Moves each servo toward its target, never faster than armStep per tick
void updateArm() {
  if (millis() - lastTick < 20) return;
  lastTick = millis();

  for (int i = 0; i < NUM_SERVOS; i++) {
    float diff = target[i] - angle[i];
    if (fabs(diff) < 0.01) continue;
    if (diff > armStep) diff = armStep;
    if (diff < -armStep) diff = -armStep;
    angle[i] += diff;
    writeServo(i, angle[i]);
  }
}

void moveAndWait(int i, float t) {
  target[i] = constrain(t, MIN_ANGLE[i], MAX_ANGLE[i]);
  while (fabs(target[i] - angle[i]) > 0.1) {
    updateArm();
    delay(5);
  }
  delay(200);
}

void testServos() {
  for (int i = 0; i < NUM_SERVOS; i++) {
    Serial.print("Testing ");
    Serial.println(SERVO_NAME[i]);
    float start = angle[i];
    moveAndWait(i, start + 15);
    moveAndWait(i, start - 15);
    moveAndWait(i, start);
  }
}

// ---------- Web handlers ----------
// The laptop's Manual tab is a different origin (http://localhost:...), so every answer says
// the browser may read it. Without this the page could send commands but never read /state.
void allowLaptopPage() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Private-Network", "true");
}

void reply(const char* type, const String &body) {
  server.sendHeader("Cache-Control", "no-store");
  allowLaptopPage();
  server.send(200, type, body);
}

String arrJson(const float* a) {
  String s = "[";
  for (int i = 0; i < NUM_SERVOS; i++) {
    s += String((int)a[i]);
    if (i < NUM_SERVOS - 1) s += ",";
  }
  return s + "]";
}

void handleRoot()  { server.send_P(200, "text/html", PAGE); }

void handleDrive() {
  if (server.hasArg("v")) driveSpeed = constrain(server.arg("v").toInt(), 100, 255);
  String d = server.arg("d");
  driveCmd(d.length() ? d[0] : 'S');
  reply("text/plain", "ok");
}

void handleServo() {
  int n = server.arg("n").toInt();
  float a = server.arg("a").toFloat();
  if (n >= 1 && n <= NUM_SERVOS) {
    int i = n - 1;
    target[i] = constrain(a, MIN_ANGLE[i], MAX_ANGLE[i]);
  }
  reply("text/plain", "ok");
}

void handleArmSpeed() {
  int v = constrain(server.arg("v").toInt(), 1, 8);
  armStep = v * 0.6;     // 0.6 .. 4.8 degrees per 20 ms
  reply("text/plain", "ok");
}

void handleHome() {
  for (int i = 0; i < NUM_SERVOS; i++) target[i] = HOME_ANGLE[i];
  reply("text/plain", "ok");
}

void handleStop() {
  drive(0, 0);
  driving = false;
  for (int i = 0; i < NUM_SERVOS; i++) target[i] = angle[i];
  reply("text/plain", "ok");
}

void handleTest() {
  reply("text/plain", "ok");
  testServos();
}

void handleState() {
  String j = "{\"a\":" + arrJson(target) + ",\"min\":" + arrJson(MIN_ANGLE) +
             ",\"max\":" + arrJson(MAX_ANGLE) + "}";
  reply("application/json", j);
}

// Browsers may ask permission first (OPTIONS) before talking to a device on the local network.
void handleNotFound() {
  allowLaptopPage();
  if (server.method() == HTTP_OPTIONS) {
    server.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
    server.sendHeader("Access-Control-Allow-Headers", "*");
    server.send(204);
    return;
  }
  server.send(404, "text/plain", "not found");
}

// ---------- Setup ----------
void setup() {
  // Force all motor pins LOW immediately so nothing moves during startup
  pinMode(IN1, OUTPUT);  digitalWrite(IN1, LOW);
  pinMode(IN2, OUTPUT);  digitalWrite(IN2, LOW);
  pinMode(IN3, OUTPUT);  digitalWrite(IN3, LOW);
  pinMode(IN4, OUTPUT);  digitalWrite(IN4, LOW);
  pinMode(ENA, OUTPUT);  digitalWrite(ENA, LOW);
  pinMode(ENB, OUTPUT);  digitalWrite(ENB, LOW);

  Serial.begin(115200);

  pwmSetup();
  drive(0, 0);

  // PCA9685
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.beginTransmission(0x40);
  if (Wire.endTransmission() == 0) {
    Serial.println("PCA9685 found at 0x40");
  } else {
    Serial.println("PCA9685 NOT FOUND - check SDA (GPIO21), SCL (GPIO22), VCC and GND");
  }

  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50);
  delay(10);

  // Servos jump to HOME at power-up: keep the arm clear of obstacles
  for (int i = 0; i < NUM_SERVOS; i++) {
    angle[i] = HOME_ANGLE[i];
    target[i] = HOME_ANGLE[i];
    writeServo(i, angle[i]);
  }

  // Join the phone hotspot (same network as the camera and the laptop); if that fails, make our own
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOST_NAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long joinStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - joinStart < WIFI_JOIN_TIMEOUT_MS) {
    delay(250);
  }
  IPAddress where;
  if (WiFi.status() == WL_CONNECTED) {
    where = WiFi.localIP();
    if (MDNS.begin(HOST_NAME)) MDNS.addService("http", "tcp", 80);
    Serial.print("Joined hotspot ");
    Serial.println(WIFI_SSID);
  } else {
    Serial.println("Could not join the hotspot (is it on, 2.4 GHz, and secrets.h right?)");
    Serial.println("Making our own network instead.");
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    where = WiFi.softAPIP();
    Serial.print("WiFi: ");
    Serial.print(AP_SSID);
    Serial.print("  password: ");
    Serial.println(AP_PASS);
  }

  server.on("/", handleRoot);
  server.on("/drive", handleDrive);
  server.on("/servo", handleServo);
  server.on("/armspeed", handleArmSpeed);
  server.on("/home", handleHome);
  server.on("/stop", handleStop);
  server.on("/test", handleTest);
  server.on("/state", handleState);
  server.onNotFound(handleNotFound);
  server.begin();

  Serial.print("Open http://");
  Serial.print(where);
  Serial.print("  or http://");
  Serial.print(HOST_NAME);
  Serial.println(".local");
}

// ---------- Loop ----------
void loop() {
  server.handleClient();
  updateArm();

  // Rover safety: stop if the page stopped sending drive commands
  if (driving && millis() - lastDriveMs > DRIVE_TIMEOUT_MS) {
    drive(0, 0);
    driving = false;
  }
}
