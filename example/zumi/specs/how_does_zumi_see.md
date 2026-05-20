---
url: https://archive.learn.robolink.com/lesson/zumi-python-how-does-zumi-see/
title: "2.1: How Does Zumi See? – Robolink Basecamp"
date: 2026-04-14T12:23:21.224Z
lang: en-US
---

We’ve moved to our new lesson portal: Robolink Learn! Lessons here will remain available until the end of June 2026.

[Visit new lessons](https://learn.robolink.com/)

### This lesson works with:

![zumi-icon](https://archive.learn.robolink.com/wp-content/themes/robolink/assets/images/zumi-icon.jpg)

Zumi

![python-icon](https://archive.learn.robolink.com/wp-content/themes/robolink/assets/images/python-icon.jpg)

Python

*   camera
*   does
*   how
*   intermediate
*   programming
*   Python
*   see
*   Zumi

### Grade level:

6 - 12+

### Approx. time required:

60 - 75 mins

  [Download as PDF](#)

###### CSTA

**3B-AP-08**

11-12

Describe how artificial intelligence drives many software and physical systems.

###### CCSS

**CCSS.ELA-Literacy.RST.11-12.2** Language Arts

Grades 11, 12

Determine the central ideas or conclusions of a text; summarize complex concepts, processes, or information presented in a text by paraphrasing them in simpler but still accurate terms.

[Read More](http://corestandards.org/ELA-Literacy/RST/11-12/2)

**CCSS.ELA-Literacy.RST.11-12.3** Language Arts

Grades 11, 12

Follow precisely a complex multistep procedure when carrying out experiments, taking measurements, or performing technical tasks; analyze the specific results based on explanations in the text.

[Read More](http://corestandards.org/ELA-Literacy/RST/11-12/3)**CCSS.ELA-LITERACY.RST.6-8.2** Language Arts

6-8

Determine the central ideas or conclusions of a text; provide an accurate summary of the text distinct from prior knowledge or opinions. **CCSS.ELA-LITERACY.RST.6-8.3** Language Arts

6-8

Follow precisely a multistep procedure when carrying out experiments, taking measurements, or performing technical tasks. 

**CCSS.ELA-Literacy.RST.9-10.2** Language Arts

Grades 9, 10

Determine the central ideas or conclusions of a text; trace the text's explanation or depiction of a complex process, phenomenon, or concept; provide an accurate summary of the text.

[Read More](http://corestandards.org/ELA-Literacy/RST/9-10/2)

**CCSS.ELA-LITERACY.RST.9-10.3** Language Arts

Grade 9-10

Follow precisely a complex multistep procedure when carrying out experiments, taking measurements, or performing technical tasks, attending to special cases or exceptions defined in the text.

**CCSS.Math.Practice.MP1** Math

High School — Geometry

Make sense of problems and persevere in solving them.

[Read More](http://corestandards.org/Math/Practice/MP1)

**CCSS.Math.Practice.MP5** Math

Grade 3

Use appropriate tools strategically.

[Read More](http://corestandards.org/Math/Practice/MP5)

**CCSS.Math.Practice.MP7** Math

Grade 5

Look for and make use of structure.

[Read More](http://corestandards.org/Math/Practice/MP7)

Step 1

## How does Zumi see?

Self-driving cars need a lot more than just obstacle detection sensors. Human drivers have eyes and ears that help us see potential dangers up ahead that a proximity detector might not be able to detect. We can also tell the different between pedestrians, cyclists, and other cars. What else do self-driving cars need to navigate our world?

Step 2

## Take a selfie

First up: use Zumi’s camera to take a picture and display it on the screen!

![Zumi - Take a selfie](https://archive.learn.robolink.com/wp-content/uploads/2020/12/Zumi-Take-a-selfie-484x277.jpg)

### Import libraries

Pay attention to the new libraries: the camera and vision libraries! These libraries contain code to take, modify, and display images.

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

from zumi.zumi import Zumi

from zumi.util.screen import Screen

import cv2

import time

from zumi.util.vision import Vision \# New library!

from zumi.util.camera import Camera \# New library!

zumi = Zumi()

camera = Camera()

screen = Screen()

vision = Vision()

from zumi.zumi import Zumi from zumi.util.screen import Screen import cv2 import time from zumi.util.vision import Vision # New library! from zumi.util.camera import Camera # New library! zumi = Zumi() camera = Camera() screen = Screen() vision = Vision()

from zumi.zumi import Zumi
from zumi.util.screen import Screen
import cv2
import time
from zumi.util.vision import Vision # New library!
from zumi.util.camera import Camera # New library!

zumi =	Zumi()
camera	= Camera()
screen	= Screen()
vision	= Vision()

Step 3

## Cheese!

Just like taking an actual picture, this code has a countdown so you can be prepared. Run the code, smile, and get ready to see yourself on the Zumi screen!

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.start\_camera() \# Turn on the camera

print("3...")

screen.draw\_text\_center("3...")

time.sleep(1)

print("2...")

screen.draw\_text\_center("2...")

time.sleep(1)

print("1...")

screen.draw\_text\_center("1...")

time.sleep(1)

screen.draw\_text\_center("Cheese!")

image = camera.capture() \# Take a picture

camera.close() \# Make sure to close the camera stream

screen.show\_image(image) \# Display image on OLED

camera.start\_camera() # Turn on the camera print("3...") screen.draw\_text\_center("3...") time.sleep(1) print("2...") screen.draw\_text\_center("2...") time.sleep(1) print("1...") screen.draw\_text\_center("1...") time.sleep(1) screen.draw\_text\_center("Cheese!") image = camera.capture() # Take a picture camera.close() # Make sure to close the camera stream screen.show\_image(image) # Display image on OLED

camera.start\_camera()	# Turn on the camera

print("3...")
screen.draw\_text\_center("3...")
time.sleep(1)
print("2...")
screen.draw\_text\_center("2...")
time.sleep(1)
print("1...")
screen.draw\_text\_center("1...")
time.sleep(1)
screen.draw\_text\_center("Cheese!")

image = camera.capture()	# Take a picture
camera.close()	# Make sure to close the camera stream
screen.show\_image(image)	# Display image on OLED

Step 4

## Displaying images in Jupyter

Instead of showing your picture on the Zumi screen, display it in Jupyter Notebook. As a bonus, it will appear in color!

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.start\_camera()

print("3...")

screen.draw\_text\_center("3...")

time.sleep(1)

print("2...")

screen.draw\_text\_center("2...")

time.sleep(1)

print("1...")

screen.draw\_text\_center("1...")

time.sleep(1)

screen.draw\_text\_center("Cheese!")

frame = camera.capture()

camera.close()

camera.show\_image(frame)

camera.start\_camera() print("3...") screen.draw\_text\_center("3...") time.sleep(1) print("2...") screen.draw\_text\_center("2...") time.sleep(1) print("1...") screen.draw\_text\_center("1...") time.sleep(1) screen.draw\_text\_center("Cheese!") frame = camera.capture() camera.close() camera.show\_image(frame)

camera.start\_camera()

print("3...")
screen.draw\_text\_center("3...")
time.sleep(1)
print("2...")
screen.draw\_text\_center("2...")
time.sleep(1)
print("1...")
screen.draw\_text\_center("1...")
time.sleep(1)
screen.draw\_text\_center("Cheese!")

frame = camera.capture()
camera.close()

camera.show\_image(frame)

Step 5

## Camera functions

There are three functions that you need to know for taking pictures with Zumi.

![Zumi - Camera functions](https://archive.learn.robolink.com/wp-content/uploads/2020/12/Zumi-Camera-functions-687x207.jpg)

Before taking a picture, you will need to turn on the camera with start\_camera(). You cannot take an image without the camera stream! The red light will indicate the camera is on. Next, use capture() to take a picture. Save the picture in a variable to display it later. For example,

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

frame = camera.capture()

frame = camera.capture()

frame = camera.capture()

Finally, don’t forget to turn off the camera! If you don’t run

close()

`close()`and you try to run

start\_camera()

`start_camera()`again, you will get an error. If this happens, save and close the notebook to force the camera to turn off.

Step 6

## Show the image

Zumi doesn’t need to “see” the image like we do to process it because all she sees is numbers! To show what we mean, write code below that takes a picture and saves it in a variable, and then print the variable.

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

\# Write code here!

camera.start\_camera()

image = camera.capture()

camera.close()

•print(image)

\# Write code here! camera.start\_camera() image = camera.capture() camera.close() •print(image)

\# Write code here!
camera.start\_camera()
image = camera.capture()
camera.close()
•print(image)

However, humans need to see the image as pixels of color to understand it. As you saw in the code above, run camera.show\_image() to show the image in Jupyter. Remember that this function takes in a parameter to know which image to show. In our example, we saved the image in the variable image. So to show the image we ran:

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.show image(image)

camera.show image(image)

camera.show image(image)

Step 7

## Changing colorspaces

If you have ever played around with Photobooth or another photo editing program, you may have seen some interesting color filters that make your pictures change colors! Depending on the task, seeing the world differently actually helps computers process images faster. Notice that we shortened the variable name image to img since you will be using this variable a lot!

![Zumi - Changing colorspaces](https://archive.learn.robolink.com/wp-content/uploads/2020/12/Zumi-Changing-colorspaces-670x592.jpg)

**Grayscale**

Grayscale is what we would normally call “black and white”. However, this is not really accurate because the image is made up of gray pixels as well. Grayscale pictures are faster to process because there are no other colors. You will be using grayscale images later to scan QR codes!

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.start\_camera()

img = camera.capture()

camera.close()

gray = vision.convert\_to\_gray(img) \# Convert it to gray

camera.show\_image(gray)

camera.start\_camera() img = camera.capture() camera.close() gray = vision.convert\_to\_gray(img) # Convert it to gray camera.show\_image(gray)

camera.start\_camera()
img = camera.capture()
camera.close()
gray = vision.convert\_to\_gray(img) # Convert it to gray
camera.show\_image(gray)

**HSV**

HSV stands for **hue**, **saturation**, and **value**. Even though the image might look strange to you, this colorspace is useful for when Zumi needs to detect or track certain colors. It is more useful than the normal colored image that you are used to seeing because each pixel of information can tell the computer about the color’s intensity and whether or not there are shadows.

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.start\_camera()

img = camera.capture()

camera.close()

hsv = vision.convert\_to\_hsv(img) \# Convert it to HSV, hue saturation and value

camera.show\_image(hsv)

camera.start\_camera() img = camera.capture() camera.close() hsv = vision.convert\_to\_hsv(img) # Convert it to HSV, hue saturation and value camera.show\_image(hsv)

camera.start\_camera()
img = camera.capture()
camera.close()
hsv = vision.convert\_to\_hsv(img) # Convert it to HSV, hue saturation and value
camera.show\_image(hsv)

**Inverted**

This one is just for fun! This filter inverts the tones of the color. For example, lighter areas become darker and darker areas become lighter.

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.start\_camera()

frame = camera.capture()

camera.close()

invert = cv2.bitwise\_not(frame) \# invert the colors

camera.show\_image(invert)

camera.start\_camera() frame = camera.capture() camera.close() invert = cv2.bitwise\_not(frame) # invert the colors camera.show\_image(invert)

camera.start\_camera()
frame = camera.capture()
camera.close()
invert = cv2.bitwise\_not(frame) # invert the colors
camera.show\_image(invert)

Step 8

## Resolution

You probably noticed that the pictures you displayed on Zumi’s screen were not very detailed. That is because the OLED screen is only 128 pixels wide and 64 pixels tall! You’ve heard us mention pixels before, but let’s look at an example. The first image is 770 pixels wide and 600 pixels tall. Each pixel is a little square of color. You can’t really see them until you zoom in.

![Zumi - Resolution1](https://archive.learn.robolink.com/wp-content/uploads/2020/12/Zumi-Resolution1-583x459.jpg)

Now look at the eyes more closely on the second image. In this image, you can see the individual pixels. There are 770 of them in one row and 600 in each column! If you had even more pixels, the picture would be considered a **high-resolution** image. In contrast, the resolution of the OLED is low.

![Zumi - Resolution2](https://archive.learn.robolink.com/wp-content/uploads/2020/12/Zumi-Resolution2-577x429.jpg)

Step 9

## Changing resolution

Although you cannot change the resolution of the OLED, you can increase the resolution of the images that the camera takes. Run the next cell to take a picture (there is not a countdown this time so be ready!). What do you think the resolution is? Guess how many pixels wide and tall the image is below:

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera.start\_camera()

img = camera.capture()

camera.show\_image(img)

camera.close()

camera.start\_camera() img = camera.capture() camera.show\_image(img) camera.close()

camera.start\_camera()
img = camera.capture()
camera.show\_image(img)
camera.close()

Try changing these values below and watch your image stretch, shrink, and get bigger! Python may round up your pixel values to fit the ratios.

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

width = 160 \# <-- CHANGE ME!

height = 128 \# <-- CHANGE ME!

camera = Camera(width,height) \# Let the camera know what changes you are making!

camera.start\_camera()

img = camera.capture()

camera.close()

camera.show\_image(img)

width = 160 # <-- CHANGE ME! height = 128 # <-- CHANGE ME! camera = Camera(width,height) # Let the camera know what changes you are making! camera.start\_camera() img = camera.capture() camera.close() camera.show\_image(img)

width = 160 # <-- CHANGE ME!
height = 128 # <-- CHANGE ME!

camera = Camera(width,height) # Let the camera know what changes you are making!
camera.start\_camera()
img = camera.capture()
camera.close()

camera.show\_image(img)

There is a size limit! Here we will take a full-resolution image. You will notice that Zumi will take more time to process and display the image. Why do you think so?

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

width = 1296 \# Largest resolution!

height = 976

camera = Camera(width,height)

camera.start\_camera()

img = camera.capture()

camera.close()

camera.show\_image(img)

width = 1296 # Largest resolution! height = 976 camera = Camera(width,height) camera.start\_camera() img = camera.capture() camera.close() camera.show\_image(img)

width = 1296 # Largest resolution!
height = 976

camera = Camera(width,height)
camera.start\_camera()
img = camera.capture()
camera.close()

camera.show\_image(img)

Step 10

## Video

Although a video looks seamless, a video is actually a series of pictures one aher the other. The images are shown so fast that you normally do not notice a difference. However, you may notice the difference here, especially if your images are very large. In order to display a video, take and display pictures inside of a for loop. Fill in the code below to show video. Since you will be using a loop, we are going to introduce two new sections of code that will help keep your program from crashing:

try

`try` and

finally

`finally`.

Plain text

Copy to clipboard

Open code in new window

EnlighterJS 3 Syntax Highlighter

camera = Camera()

camera.start\_camera()

try:

for x in range(30):

\# TODO Take a picture

\# TODO show the picture

camera.clear\_output() \# Clear the output for the next image to show

finally:

camera.close()

camera = Camera() camera.start\_camera() try: for x in range(30): # TODO Take a picture # TODO show the picture camera.clear\_output() # Clear the output for the next image to show finally: camera.close()

camera = Camera()
camera.start\_camera()

try:
    for x in range(30):
        # TODO Take a picture
        # TODO show the picture
        camera.clear\_output() # Clear the output for the next image to show
finally:
    camera.close()

If anything goes wrong or you stop your code while in the try section, the program will automatically jump to the

finally

`finally` statements. In this case, we put a

close()

`close()` for the camera so that you never have to worry about it staying on.

[Log in to mark complete](https://archive.learn.robolink.com/login/)

 Search for: Search

##### Recent Comments

* * *

##### Archives

* * *

##### Categories

* * *

*   No categories

##### Meta

* * *

*   [Log in](https://archive.learn.robolink.com/login/)
*   [Entries feed](https://archive.learn.robolink.com/feed/)
*   [Comments feed](https://archive.learn.robolink.com/comments/feed/)
*   [WordPress.org](https://wordpress.org/)

##### Working Hours

* * *

*   Monday 9am - 6pm
*   Tuesday 9am - 6pm
*   Wednesday 9am - 6pm
*   Thursday 9am - 6pm
*   Friday 9am - 6pm
*   Saturday _Closed_
*   Sunday _Closed_

##### Latest Posts

* * *

You are leaving Robolink's Basecamp lesson portal. Please be aware that any website outside of our Basecamp lesson portal will be subject to privacy policies different from this website.

[Stay on this site](#) [Continue to external site](#)

You are currently offline. The link that you clicked is not accessible in offline mode. If you need to access the link, you will need to connect your device online.

[Close](#)

You are offline. Basecamp running in offline mode.

[](#top)