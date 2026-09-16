# The History of Pi

<!-- 来源：Gemini 对话（share.gemini.google/6bKWnzs2Ol8h） · 原文 8238 字符 · 汉字占比 1% -->

π

): From Geometrical Bounds to Supercomputing Limits

The ratio of a circle's circumference to its diameter, denoted by the Greek letter

π

, has captivated mathematicians for thousands of years. The history of computing

π

reflects the evolution of mathematics itself—shifting from physical measurements to geometric polygon bounds, transitioning to infinite series, and culminating in modern computer algorithms.

1. Ancient Approximations: Physical Measurement and Early Geometry

In antiquity, civilizations recognized that the ratio of a circle's circumference to its diameter was slightly greater than

3

.

Babylonia and Egypt (c. 1900–1600 BCE):

The Babylonians used the approximation

8

25

​

=

3.125

. The Egyptian

Rhind Papyrus

(c. 1650 BCE) derived an area formula yielding

(

9

16

​

)

2

≈

3.1605

.

Archimedes of Syracuse (c. 250 BCE):

Archimedes pioneered the

polygon approximation method

. By inscribing and circumscribing regular

96

-gons around a circle, he proved:

3

71

10

​

<

π

<

3

7

1

​

(

3.1408

<

π

<

3.1428

)

Archimedes' Polygon Method

Inscribed Polygon < Circle < Circumscribed Polygon

/────\         /────\

/  /\  \       / │  │ \

│  │  │  │ <   │  │  │  │

\  \/  /       \ │  │ /

\────/         \────/

2. The Chinese Milestone: Polygon Perfection

Chinese mathematicians advanced polygon-based computation to its absolute mathematical limits long before the advent of calculus.

Evolution of Chinese Calculation

│

┌─────────────────────────────┴─────────────────────────────┐

▼                                                           ▼

┌─────────────────────────┐                         ┌─────────────────────────┐

│ Liu Hui (刘徽, 263 CE)  │                         │ Zu Chongzhi (祖冲之, c. 480 CE)│

│ Cut-circle method with  │                         │ Calculated using a      │

│ a 3072-gon;             │ ──────────────────────> │ 24,576-gon;             │

│ Found π ≈ 3.1416        │                         │ 7 accurate decimal digits│

└─────────────────────────┘                         └─────────────────────────┘

Liu Hui (刘徽, 263 CE):

Formulated the

Haidao Suanjing

and created the "cut-circle method" (割圆术). By calculating the perimeter of a regular

3

,

072

-gon, he derived

π

≈

3.1416

.

Zu Chongzhi (祖冲之) and Zu Shengzhi (祖暅) (c. 480 CE):

Using counting rods (

chousuan

) without digital tools, Zu Chongzhi computed the perimeter of a regular

24

,

576

-gon

, pinning

π

between two bounds:

3.1415926

<

π

<

3.1415927

He also identified two famous rational fractions:

Milü (密率 - Close Ratio):

113

355

​

≈

3.1415929

(accurate to

6

decimal places)

Yuelü (约率 - Approximate Ratio):

7

22

​

≈

3.1428

Zu Chongzhi’s

7

-decimal-place precision remained an unbroken world record for over

1

,

000

years until Madhava and Jamshīd al-Kāshī in the 15th century.

3. The Analytical Era: Infinite Series and Calculus

With the birth of calculus in Europe, mathematicians abandoned physical polygons in favor of

infinite series

, allowing

π

to be calculated to hundreds of digits algebraically.

Madhava of Sangamagrama (c. 1400):

The Indian mathematician discovered the infinite series for arctangent, now known as the Madhava-Leibniz series:

arctan

(

x

)

=

x

−

3

x

3

​

+

5

x

5

​

−

7

x

7

​

+

⋯

Setting

x

=

1

yields:

4

π

​

=

1

−

3

1

​

+

5

1

​

−

7

1

​

+

⋯

John Machin (1706):

Machin devised a rapidly converging arctangent identity that dominated

π

calculations for centuries:

4

π

​

=

4

arctan

(

5

1

​

)

−

arctan

(

239

1

​

)

4. The Computer Age & Fabrice Bellard's Milestones

The mid-20th century transformed

π

calculation from hand written formulas into benchmarks for supercomputing architecture and arbitrary-precision arithmetic.

Modern Computing Paradigms

│

┌─────────────────────────────┴─────────────────────────────┐

▼                                                           ▼

┌─────────────────────────┐                         ┌─────────────────────────┐

│ Gauss-Legendre / AGM    │                         │ Ramanujan-Chudnovsky    │

│ Quadratically converging;│                         │ Hypergeometric series;  │

│ Doubles accurate digits │                         │ Yields ~14 digits per   │

│ every iteration step.   │                         │ evaluated term.         │

└─────────────────────────┘                         └─────────────────────────┘

The Chudnovsky Algorithm

Published by the Chudnovsky brothers in 1987, this hypergeometric series is the basis for most contemporary record attempts:

π

1

​

=

12

k

=

0

∑

∞

​

(

3

k

)!

(

k

!

)

3

(

640320

)

3

k

+

3/2

(

−

1

)

k

(

6

k

)!

(

545140134

k

+

13591409

)

​

Fabrice Bellard's Breakthroughs

French computer programmer

Fabrice Bellard

(creator of FFmpeg, QEMU, and QuickJS) made monumental contributions to

π

calculation:

Bellard's Formula (1997):

Bellard improved upon the BBP algorithm (Bailey–Borwein–Plouffe) to extract isolated

n

-th binary digits of

π

significantly faster:

π

=

2

6

1

​

k

=

0

∑

∞

​

2

10

k

(

−

1

)

k

​

(

−

4

k

+

1

2

5

​

−

4

k

+

3

1

​

+

10

k

+

1

2

8

​

−

10

k

+

3

2

6

​

−

10

k

+

5

2

2

​

−

10

k

+

7

2

2

​

+

10

k

+

9

1

​

)

The 2.7 Trillion Digit World Record (2009):

On December 31, 2009, Bellard broke the world record by computing

π

to

2.7

trillion decimal places

.

Hardware Efficiency:

Unlike previous supercomputer runs requiring tens of millions of dollars in hardware, Bellard accomplished this on a single desktop PC costing under

$3

,

000

, running for 131 days.

TNC Program:

He authored

TNC

(

pi_chudnovsky

), an ultra-optimized C program leveraging disk-swap caching and Fast Fourier Transform (FFT) multiplication algorithms.

5. Timeline of Historical

π

Records

Era / Year

Mathematician / System

Method / Algorithm

Precision / Digits

c. 250 BCE

Archimedes

Inscribed

96

-gon

2

decimal places (

3.14

)

c. 480 CE

Zu Chongzhi (祖冲之)

Cut-circle method (

24

,

576

-gon)

7

decimal places

1706

John Machin

Machin-like Arctangent Series

100

decimal places

1949

ENIAC (Reitwiesner et al.)

Machin's Formula on Vacuum Tubes

2

,

037

digits

2009

Fabrice Bellard

Chudnovsky Algorithm on Desktop PC

2.7

×

1

0

12

digits (

2.7

Trillion)

Modern Era

Cloud Supercomputers (y-cruncher)

Chudnovsky Algorithm + FFT Multiplication

>

100

×

1

0

12

digits (

100

+

Trillion)

Vocabulary

Inscribed Polygon

/ɪnˈskraɪbd ˈpɑːliɡɑːn/

n.

内接多边形

Circumscribed Polygon

/ˈsɜːrkəmˌskraɪbd ˈpɑːliɡɑːn/

n.

外切多边形

Cut-circle Method

/kʌt ˈsɜːrkl ˈmeθəd/

n.

割圆术

Counting Rods

/ˈkaʊntɪŋ rɑːdz/

n.

筹算；算筹

Convergent Series

/kənˈvɜːrdʒənt ˈsɪriːz/

n.

收敛级数

Arbitrary-Precision Arithmetic

/ɑːrbɪtreri prɪˈsɪʒn əˈrɪθmətɪk/

n.

任意精度算术（高精度计算）

Fast Fourier Transform (FFT)

/fæst ˈfʊrieɪ trænsˈfɔːrm/

n.

快速傅里叶变换（用于超大整数快速乘法）

Reading Comprehension Quiz

I. Multiple Choice

How did Zu Chongzhi calculate

π

to 7 decimal places in 5th-century China?

A. By using early trigonometric infinite series formulas.

B. By applying the cut-circle method to calculate the perimeter of a 24,576-sided polygon using counting rods.

C. By building a mechanical pendulum device to measure physical circles.

What was revolutionary about Fabrice Bellard's 2009 world record of 2.7 trillion digits?

A. He used an abacus instead of a computer.

B. He proved that

π

is a rational number.

C. He achieved supercomputer-level precision on a standard desktop computer using optimized C code and FFT algorithms.

II. True or False

Archimedes calculated

π

using infinite series derived from calculus. (

T / F

)

Answer Key

B

(

Explanation:

Zu Chongzhi extended Liu Hui's cut-circle method to a

24

,

576

-gon using physical counting rods, reaching unprecedented precision.)

C

(

Explanation:

Bellard wrote highly efficient C programs using disk-caching FFT algorithms to calculate

2.7

trillion digits on an inexpensive desktop PC.)

F

(

Explanation:

Archimedes used geometric polygons inscribed and circumscribed around a circle, hundreds of years before calculus was invented.)

Explore deeper into numerical algorithms and history:

Explain how the Chudnovsky algorithm and FFT multiplication work

Explore the mathematical proof that Pi is irrational and transcendental
