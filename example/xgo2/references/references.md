Title: Develop and use based on Python | LEARN

URL Source: https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development

Markdown Content:
XGO-lite V2 has built-in motion control library file xgolib.py, education library xgoedu.py and advanced library xgoadvance.py, developers can directly call related interface functions to control the robot dog.

Sports library download [xgolib.py(26 KB)](https://www.elecfreaks.com/download/xgolib.py)

## Initialization[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#initialization "Direct link to heading")

The following is the initialization code:

```
#import xgolib
from xgolib import XGO
#instantiate dog
dog = XGO(port='/dev/ttyAMA0',version="xgolite")
```

## Determine the type of robot dog[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#determine-the-type-of-robot-dog "Direct link to heading")

Since xgolite and xgomini have different motion performance and parameters, in order to accurately control the motion of the robot dog, you can use:

**dog.read_firmware()** function detects the type of robot dog

Sample code:

```
from xgolib import XGO
dog = XGO(port='/dev/ttyAMA0',version="xgolite")
version=dog.read_firmware()
if version[0]=='M':    
    print('XGO-MINI')    
    dog = XGO(port='/dev/ttyAMA0',version="xgomini")    
    dog_type='M'
else:    
    print('XGO-LITE')    
    dog_type='L'
```

The type of the dog can be judged through this piece of code. If the variable dog_type is 'M', the type of the dog is XGOMINI, and if it is 'L', the type of the dog is XGOLITE.

## Motion Control Library Introduction[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#motion-control-library-introduction "Direct link to heading")

#### Pan back and forth[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#pan-back-and-forth "Direct link to heading")

**Move(direction, step)**

| parameter name | Format | input range | illustrate |
| --- | --- | --- | --- |
| direction | character | 'x'、'X'、'y'、'Y' | 'x' or 'X' makes the dog move forward or backward, 'y' or 'Y' makes the dog move left or right |
| step | number | x:[-25,25],y:[-18,18] | This parameter represents the translation step size. According to the direction, a positive value represents forward or left movement, and a negative value represents backward or right movement. When the input value exceeds the range, it moves according to the limit value. |

#### To rotate[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#to-rotate "Direct link to heading")

**Turn(step)**

| Parameter name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| step | number | [-150,150] | This parameter represents the rotation speed, the unit is °/s, the positive value is left rotation, and the negative value is right rotation. |

#### No progress[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#no-progress "Direct link to heading")

**mark_time(data)**

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| data | number | [10,35] | This parameter represents the height of leg raising when standing still, the unit is mm, when the input is 0, stop standing still |

#### Change the frequency of strides[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#change-the-frequency-of-strides "Direct link to heading")

pace(mode) speed = stride frequency x stride length

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| mode | string | ['normal','slow','high'] | This parameter represents the stride frequency, normal is the default stride frequency, low is the slow stride frequency, and high is the high-speed stride frequency |

#### Stop moving[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#stop-moving "Direct link to heading")

**Stop()**

**Examples of mobile related methods**

`#The robot dog advances in 18mm stepsdog.move('x',18)#The robot dog moves to the right with a step size of 5mmdog.move('y',-5)#The code in the next sentence can be executed normally, and it will move to the left by 18mmdog.move('Y',30)#The robot dog turns left at a speed of 60°/sdog.turn(60)#The robot dog moves at a high pacedog.pace('high')#The robot dog walks on the spot with a leg height of 25mmdog.mark_time(25)#The robot dog stops walking in placedog.mark_time(0)#robot dog stops movingdog.stop()`

Based on these methods, a series of methods are encapsulated in the library for easy use.

| Method name | Illustrate |
| --- | --- |
| move_x(step) | Move back and forth, equivalent to move ('x ', step) |
| move_y(step) | Moving left and right, equivalent to move ('y ', step) |
| forward(step) | Forward, equivalent to move ('x ', abs (step)) |
| back(step) | Step back, equivalent to move ('x ', - abs (step)) |
| left(step) | Left shift, equivalent to move ('y ', abs (step)) |
| right(step) | Right shift, equivalent to move ('y ', - abs (step)) |
| turnleft(step) | Turn left, equivalent to turn (abs (step)) |
| turnright(step) | Turn right, equivalent to turn (- abs (step)) |

When adjusting the posture, the position of the four legs of the robot dog will not change, but the position or angle of the body will change.

#### Body position translation[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#body-position-translation "Direct link to heading")

**Translation(direction, data)**

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| direction | Single character or character list | 'x', 'y', 'z' or a list containing the above values | 'x' represents forward and backward translation, 'y' represents left and right translation, and 'z' represents height |
| data | Number | x:[-35,35],y:[-18,18],z:[75,115] | This parameter represents the translation distance of the fuselage position, in millimeters |

#### Body attitude adjustment[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#body-attitude-adjustment "Direct link to heading")

**attitude(direction, data)**

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| direction | Single character or character list | 'r', 'p', 'y' or a list containing the above values | 'r' represents roll angle, 'p' represents pitch angle, and 'y' represents yaw angle |
| data | Number | r:[-20,20],p:[-15,15],y:[11,11] | This parameter represents the amplitude of aircraft attitude adjustment, in degrees |

#### Periodic translation of the fuselage[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#periodic-translation-of-the-fuselage "Direct link to heading")

**Periodic_tran(direction, period)**

The machine dog body will undergo reciprocating translation in the specified period and direction, with an amplitude of half the limit value of position translation, and can perform periodic motion in multiple directions simultaneously. The periodic movement of the fuselage and the movement of the entire machine cannot be carried out simultaneously.

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| direction | Single character or character list | 'x', 'y', 'z' or a list containing the above values | 'x' represents forward and backward translation, 'y' represents left and right translation, and 'z' represents height |
| period | Number | [1.5,8] | This parameter represents the motion period, in seconds; Entering 0 represents stopping movement |

#### Periodic rotation of the fuselage[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#periodic-rotation-of-the-fuselage "Direct link to heading")

**Periodic_rot(direction, period)**

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| direction | Single character or character list | r', 'p', 'y' or a list containing the above values | 'r' represents roll angle, 'p' represents pitch angle, and 'y' represents yaw angle |
| period | Number | [1.5,8] | This parameter represents the motion period, in seconds; Entering 0 represents stopping movement |

**Examples of pose related methods**

`#Forward translation of the fuselage by 18mmdog.translation('x',18)#Translate the body to the right by 10mm, and set the height to 100mm#You can enter a single value or a list to control movement in multiple directionsdog.translation(['y','z'],[-10,100])#The pitch angle of the fuselage is set to 10 °, the yaw angle is set to -4 °, and the roll angle is set to 8 °dog.attitude(['p','y','r'],[10,-4,8])#The body moves back and forth in a cycle of 3 secondsdog.periodic_tran('x',3)#The fuselage undergoes rolling angle reciprocating rotation at a period of 3 seconds, and yaw angle reciprocating rotation at a period of 7.4 secondsdog.periodic_rot(['r','y'],[3,7.4])#Stop the reciprocating rotation of yaw angledog.periodic_rot('y',0)`

#### Set the end position of the robotic arm[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#set-the-end-position-of-the-robotic-arm "Direct link to heading")

**Arm( arm_x, arm_z)**

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| arm_x | float | [-80, 155] | Unit: mm |
| arm_z | float | [-95, 155] | Unit: mm |

The coordinates x and z here are relative to the base of the robotic arm, in millimeters.

When the value exceeds the workspace of the robotic arm, the robotic arm will maintain the posture corresponding to the last valid value. For example, the posture corresponding to (155,0) is extended forward to the maximum, (0155) is extended upward to the maximum, and (155155) is inclined upward to the maximum. However, if the robotic arm cannot reach this position, it will maintain the valid position sent last time.

#### Set the mechanical arm gripper to open and close[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#set-the-mechanical-arm-gripper-to-open-and-close "Direct link to heading")

**Claw(pos)**

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| pos | uint_8 | 0-255 | 0 corresponds to fully open, 255 corresponds to fully closed |

#### Set whether the robotic arm is in stable mode[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#set-whether-the-robotic-arm-is-in-stable-mode "Direct link to heading")

**Arm_mode(mode)**

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| mode | bool | 0\1 | 0 not turned on, 1 turned on |

After opening, the end of the robotic arm will not translate with the body's translation (translation refers to the movement of the trunk with four feet standing, rather than walking forward, backward, left, or right).

### Other methods[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#other-methods "Direct link to heading")

#### Restore initial state[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#restore-initial-state "Direct link to heading")

**Reset()**

Stop all movements and restore all states to their initial state

#### Set self stable state[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#set-self-stable-state "Direct link to heading")

**imu(mode)**

In a self stable state, the robotic dog will automatically adjust its posture angle to maintain its back in a horizontal position, and cannot be manually set when turned on.

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| mode | integer | 0, 1 | 0 represents off, 1 represents on |

**Perform(mode)**

In performance mode, the robot dog will cycle through the preset actions.

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| mode | integer | 0, 1 | 0 represents off, 1 represents on |

#### Single leg control[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#single-leg-control "Direct link to heading")

**leg(leg_id, data)**

Control the position feet end of the designated leg(s)

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| leg_id | integer | 1, 2, 3, 4 | Representing left front leg, right front leg, right rear leg, and left rear leg respectively |
| data | List of numbers with a length of 3 | x:[-35,35],y:[-18,18],z:[75,115] | Representing left front leg, right front leg, right rear leg, and left rear leg respectively |

**Examples of other methods**

`#Set the coordinates of the foot end of the right front leg to(10mm,-12mm,90mm)dog.leg(2,[10,-12,90])`

#### Servo control[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#servo-control "Direct link to heading")

**motor(motor_id, data)**

Control the rotation angle of the servo

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| motor_id | Integer or integer list | [11,12,13,21,22,23,31,32,33,41,42,43] | The first digit represents the leg where the steering gear is located, and the second digit represents the position on that leg, which is 1, 2, and 3 from bottom to top |
| data | Number or number list | Lower: [-65, 73], Middle: [-66, 93], Upper: [-31, 31] | This parameter represents the foot position in degrees |

**Example of servo**

`#Set the steering gear rotation angle in the right front leg to 30 °dog.motor(22,30)#Set the rotation angle of the steering gear on the right front leg to 10 °, and the rotation angle of the steering gear on the left rear leg to -20 °dog.motor([23,41],[10,-20])`

#### Single leg servo unloading[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#single-leg-servo-unloading "Direct link to heading")

**Unload_motor(leg_id)**

Unload the three servo motors on one leg without outputting torque, and then freely rotate them by hand, usually used for writing actions

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| leg_id | integer | 1,2,3,4 | Representing left front leg, right front leg, right rear leg, and left rear leg respectively |

#### All servo unloading[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#all-servo-unloading "Direct link to heading")

**Unload_allmotor()**

Unload all servo motors without outputting torque, and rotate them freely by hand

#### Single leg servo loading[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#single-leg-servo-loading "Direct link to heading")

**Load_motor(leg_id)**

Keep the three servo motors on one leg loaded in their current positions, output torque, and do not rotate them by hand afterwards. Usually used for writing actions

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| leg_id | integer | 1,2,3,4 | Representing left front leg, right front leg, right rear leg, and left rear leg respectively |

#### All servo loads[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#all-servo-loads "Direct link to heading")

**load_allmotor()**

Keep all servo motors loaded in their current positions, output torque, and do not rotate them by hand afterwards

#### Set the rotation speed of the steering gear[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#set-the-rotation-speed-of-the-steering-gear "Direct link to heading")

**motor_speed(speed)**

Adjusting the rotation speed of the steering gear is suitable for individual control of the servo

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| speed | integer | [0,255] | 0 is the lowest speed, 255 is the highest speed |

#### Modify Bluetooth name[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#modify-bluetooth-name "Direct link to heading")

**bt_rename(name)**

Modify the Bluetooth name again, and Bluetooth will disconnect after calling this function

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| name | character string | Length not greater than 10 | The Bluetooth name format of the robot dog is XGO_ Xxx, xxx is a modifiable part that only supports characters in the ascii code. |

#### Execute preset actions[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#execute-preset-actions "Direct link to heading")

**action(action_id)**

| Parameter Name | Format | Input rangeI | llustrate |
| --- | --- | --- | --- |
| action_id | integer | [1,255] | The corresponding relationship between ID and action is shown in the table below |

| ID | Action | ID | Action | ID | Action |
| --- | --- | --- | --- | --- | --- |
| 1 | get down | 2 | Stand up | 3 | Crawling forward |
| 4 | circle | 5 | marking time | 6 | Squat |
| 7 | Rotate Roll | 8 | Rotate Pitch | 9 | Rotate Yaw |
| 10 | Three axis rotation | 11 | Pee | 12 | Sit down |
| 13 | Wave | 14 | Stretch oneself | 15 | Wave |
| 16 | Swing left and right | 17 | Seeking food | 18 | Find food |
| 19 | Handshake | 20 | New Year's greetings |  |  |

#### Calibrate the position of the steering gear[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#calibrate-the-position-of-the-steering-gear "Direct link to heading")

**calibration(state)**

If there is a significant position deviation of some joints after startup, this function can be called for calibration. Please use with caution in other situations

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| state | integer | [0,1] | 1. Enter the calibration state, at which point the servo is unloaded, and then place the robotic dog in the calibration state, with the lower legs parallel to the ground, the thighs at 90 ° to the torso, and the torso parallel to the ground; 0 complete calibration |

#### Reading the servo angle[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#reading-the-servo-angle "Direct link to heading")

**read_motor()**

Read the angles of 12 servo motors. If the reading is successful, a list with a length of 12 will be returned, corresponding to the servo motor angles numbered [11,12,13,21,23,23,31,33,41,42,43]. If the reading fails, an empty list will be returned

#### Read battery level[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#read-battery-level "Direct link to heading")

**read_battery()**

Reads the current battery level, returns an integer from 1 to 100 for successful reading, representing the percentage of remaining battery level, and returns 0 for failed reading.

#### Read attitude angle[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#read-attitude-angle "Direct link to heading")

**read_roll()**

**read_pitch()**

**read_yaw()**

Read the current attitude angle. If the reading succeeds, it will be a floating point number. If the reading fails, it will return 0

## Introduction to Education Library[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#introduction-to-education-library "Direct link to heading")

XGO lite V2 has an education library file xgoedu.py built-in, which can be directly imported and used.

You can also download it here：[https://github.com/Xgorobot/XGO-PythonLib](https://github.com/Xgorobot/XGO-PythonLib)

### initialization[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#initialization-1 "Direct link to heading")

The following is the initialization code:

`#import xgoedufrom xgoedu import XGOEDU#instantiate eduedu = XGOEDU()`

### Screen drawing[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#screen-drawing "Direct link to heading")

**You need to kill the self starting main.py process first, otherwise there will be a screen refresh conflict**

#### draw a straight line[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#draw-a-straight-line "Direct link to heading")

lcd_line(x1,y1,x2,y2,color=(r,g,b),width=width)

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| x1,y1,x2,y2 | digit | x1 x2:[0,320] y1 y2:[0,240] | X1, y1 is the initial point label x2, and y2 is the endpoint coordinates |
| Color (can be defaulted) Default to white | Rgb tuple | r g b:[0,255] | Color is the line color |
| Width (can be defaulted) defaults to 2 | digit |  | Width is the line width |

#### Draw an arc with width for the line width[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#draw-an-arc-with-width-for-the-line-width "Direct link to heading")

lcd_circle(x1,y1,x2,y2,angle0,angle1,color=(255,255,255),width=2)

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| x1,y1,x2,y2 | digit | x1 x2:[0,320] y1 y2:[0,240] | x1，y1，x2，y2 define two points for a given border |
| angle0,angle1 | digit | angle0 angle1:[0,360] | Angle0 is the initial degree, angle1 is the ending angle |
| Color (can be defaulted) Default to white | Rgb tuple | r g b:[0,255] | Color is the color of the arc |
| Width (can be defaulted) defaults to 2 | digit |  | Width is the width of the arc |

#### Draw a rectangle[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#draw-a-rectangle "Direct link to heading")

lcd_rectangle(x1,y1,x2,y2,fill=None,outline=(255,255,255),width=2)

| Parameter Name | Format | input range | illustrate |
| --- | --- | --- | --- |
| x1,y1,x2,y2 | digit | x1 x2:[0,320] y1 y2:[0,240] | X1, y1 is the initial point label x2, and y2 is the endpoint coordinates |
| Fill (can be defaulted) The default is None | Rgb tuple | r g b:[0,255] | Fill is the fill color, and None is not filled |
| Outline (can be defaulted) Default to white | Rgb tuple | r g b:[0,255] | Width is the line color |
| Width (can be defaulted) defaults to 2 | digit |  | Width is the line width |

#### Display text[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#display-text "Direct link to heading")

Can display Chinese and English using Microsoft Yahei font, with adjustable font sizelcd_text(x,y,content,color=(255,255,255),,fontsize=15)

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| x,y | digit | x y:[0,320] | x. y is the initial point marker |
| content | character string |  | Content is the displayed content |
| Color (can be defaulted) Default to white | Rgb tuple | r g b:[0,255] | Color is the line color |
| Fontsize (can be defaulted) The default is 15 | digit |  | Fontsize is the font size |

#### Display picture[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#display-picture "Direct link to heading")

lcd_picture(filename,x=0,y=0)

| Parameter Name | Format | Input range | Ilustrate |
| --- | --- | --- | --- |
| filename | character string |  | Image file path, please use jpg images |
| x. Y (can be defaulted) Default x, y is 0 | digit | x y:[0,320] | x. Y is the initial point marker |

#### Clear screen[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#clear-screen "Direct link to heading")

lcd_clear()

### Key detection[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#key-detection "Direct link to heading")

xgoButton(button)

| Parameter Name | Format | Input range | Return value |
| --- | --- | --- | --- |
| button | Specify string | ["a","b","c","d"] | False not pressed True pressed |

## Audio function[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#audio-function "Direct link to heading")

### PLAY AUDIO[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#play-audio "Direct link to heading")

xgoSpeaker(filename)

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| filename | character string |  | Audio file path |

### Recording audio[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#recording-audio "Direct link to heading")

xgoAudioRecord(filename="record.wav",seconds=5)

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| Filename (can be defaulted) The default is "record. wav" | character string |  | File name for recording audio |
| Seconds (can be defaulted) The default is 5 | digit |  | The length of the recorded file in seconds |

## Camera function[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#camera-function "Direct link to heading")

### Turn on the camera[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#turn-on-the-camera "Direct link to heading")

cameraOn(filename="camera")

After calling the API, it will enter camera mode. Press a key to take photos, b key to start recording, b key to stop again, and c key to exit

| Parameter Name | Format | Input range | Illustrate |
| --- | --- | --- | --- |
| Filename (can be defaulted) Default "camera" | character string |  | File name for taking photos and videos. Save photos in jpg format and videos in mp4 format |

## AI function[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#ai-function "Direct link to heading")

The core function of this series of APIs is to retrieve a frame of image for analysis and return the results. It can be used to detect a single image by passing parameters into the path of the image. To analyze the camera image in real-time, please use it in conjunction with while. The following is the example code:

Gesture recognition single picture:

`#input xgoedufrom xgoedu import XGOEDU#Instantiating eduedu = XGOEDU()#Gesture recognition for camera.jpg in the same level directoryresult=edu.gestureRecognition("camera.jpg")#Print recognition resultsprint(result)`

Real time gesture recognition via camera:

`#input xgoedufrom xgoedu import XGOEDU#Instantiating eduedu = XGOEDU()#Cycle through camera recognition, press the c key to exitwhile True:    result=edu.gestureRecognition()  #Default parameter, using camera recognition by default    print(result)    if dog.xgoButton("c"):   #Press the c key to exit the cycle        break`

### Gesture recognition[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#gesture-recognition "Direct link to heading")

gesture Recognition(target="camera")

| Parameter Name | Format | Illustrate | Return value |
| --- | --- | --- | --- |
| Target (can be defaulted) The default "camera" is to use the camera to capture images | character string | Target is the path to the image file | (ges,(x,y)) GES is the result of gesture recognition The gestures currently included include： ["1","2","3","4","5","Good","Ok","Rock","Stone"] Coordinate value xy |

### YOLO identification[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#yolo-identification "Direct link to heading")

yoloFast(target="camera")

| Parameter Name | Format | Illustrate | Return value |
| --- | --- | --- | --- |
| Target (can be defaulted) The default "camera" is to use the camera to capture images | character string | Target is the path to the image file | (object,(x,y)) Object is YOLO recognition result The objects currently included are： ['person','bicycle','car','motorbike','aeroplane','bus','train','truck','boat','trafficlight','firehydrant','stopsign','parkingmeter','bench','bird','cat','dog','horse','sheep','cow','elephant','bear','zebra','giraffe','backpack','umbrella','handbag','tie','suitcase','frisbee','skis','snowboard','sportsball','kite','baseballbat','baseballglove','skateboard','surfboard','tennisracket','bottle','wineglass','cup','fork','knife','spoon','bowl','banana','apple','sandwich','orange','broccoli','carrot','hotdog','pizza','donut','cake','chair','sofa','pottedplant','bed','diningtable','toilet','tvmonitor','laptop','mouse','remote','keyboard','cell phone','microwave','oven','toaster','sink','refrigerator','book','clock','vase','scissors','teddy bear','hair drier','toothbrush'] 坐标值xy |

### Face recognition[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#face-recognition "Direct link to heading")

face_detect(target="camera")

| Parameter Name | Format | Illustrate | Return value |
| --- | --- | --- | --- |
| Target (can be defaulted) The default "camera" is to use the camera to capture images | character string | Target is the path to the image file | [x, y, w, h] The x-coordinate, y-coordinate, width, height of the facial recognition frame |

### Emotional recognition[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#emotional-recognition "Direct link to heading")

emotion(target="camera")

| Parameter Name | Format | Illustrate | Return value |
| --- | --- | --- | --- |
| Target (can be defaulted) The default "camera" is to use the camera to capture images | character string | Target is the path to the image file | (emotion,(x,y)) emotion contain: ['Angry','Happy','Neutral','Sad','Surprise'] Coordinate value xy |

### Age and gender recognition[​](https://wiki.elecfreaks.com/en/pico/cm4-xgo-robot-kit/advanced-development/python-development#age-and-gender-recognition "Direct link to heading")

agesex(target="camera")

| Parameter Name | Format | Illustrate | Return value |
| --- | --- | --- | --- |
| Target (can be defaulted) The default "camera" is to use the camera to capture images | character string | Target is the path to the image file | (gender,age,(x,y)) gender contain['Male', 'Female'] age contain['(0-2)', '(4-6)', '(8-12)', '(15-20)', '(25-32)', '(38-43)', '(48-53)', '(60-100)'] Coordinate value x，y |

