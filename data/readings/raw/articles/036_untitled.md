# （无标题）

<!-- 来源：Gemini 对话（share.gemini.google/6bKWnzs2Ol8h） · 原文 7674 字符 · 汉字占比 0% -->

Adaptive Optics (AO) is a real-time feedback technology used in ground-based observatories to eliminate the blurring effect caused by Earth's atmosphere.

When starlight travels through the atmosphere, temperature and density fluctuations mix pockets of air with different refractive indices. This distorts the flat wavefronts of starlight into jagged, irregular surfaces—a phenomenon astronomers call atmospheric "seeing." Adaptive Optics measures these wavefront distortions hundreds to thousands of times per second and applies inverse physical deformations to a flexible mirror to restore razor-sharp image clarity.

Opens in a new window

The layout of laser guide star AO system at Subaru Telescope. AO ...

A modern Laser Guide Star AO setup on a major ground-based observatory.

Source: ResearchGate

The Closed-Loop Feedback Architecture

An AO system operates as a continuous, high-speed closed loop consisting of four primary components:

Adaptive Optics Feedback Loop

Distorted Light ──> [ Deformable Mirror ] ──> Corrected Light ──> Science Camera

▲                         │

│                         ▼

[ Real-Time Computer ] <── [ Wavefront Sensor ]

Light Collection:

Distorted starlight enters the main telescope aperture and strikes a

Deformable Mirror (DM)

.

Sampling:

A beam splitter directs a fraction of the reflected light toward a

Wavefront Sensor (WFS)

while sending the corrected science light to the astronomical instruments.

Measurement:

The Wavefront Sensor (most commonly a

Shack-Hartmann sensor

) splits the incoming beam using an array of tiny micro-lenses. Each microlense focuses light onto a small focal spot; by tracking the displacement of these spots relative to their ideal reference positions, the sensor calculates local tilt vectors across the entire wavefront.

Real-Time Computation:

High-speed processors convert the spatial slope measurements into a digital phase map using matrix operations. The computer determines the exact mirror shape required to counteract the phase error.

Correction:

Signals are sent to the actuators beneath the Deformable Mirror, updating its physical shape at rates between

500

Hz

and

2

,

000

Hz

—faster than the atmospheric turbulence shifts.

The Role of Deformable Mirrors (DMs)

The Deformable Mirror acts as the primary corrective element. Unlike rigid glass primary mirrors, a DM features a thin, flexible reflective faceplate (often less than a millimeter thick) mounted atop a high-density grid of precision actuators.

Deformable Mirror Mechanism

[ Flexible Reflective Faceplate ]

▲       ▲       ▲       ▲

│       │       │       │

[ Act1 ] [ Act2 ] [ Act3 ] [ Act4 ]  (Piezoelectric / MEMS)

│       │       │       │

────────────────────────────────

Rigid Support Substrate

Actuator Technologies:

Piezoelectric Actuators:

Ceramics that expand or contract in response to microscopic voltage changes, exerting physical pushes and pulls on the mirror backplate.

Voice Coils (Secondary AO Mirrors):

Electromagnetic actuators similar to loudspeaker coils. Some modern giant telescopes (like the Very Large Telescope and Large Binocular Telescope) use deformable secondary mirrors supported by over 1,000 magnetic voice coils levitating a ultra-thin shell.

MEMS (Micro-Electro-Mechanical Systems):

Silicon-based miniature arrays used in ultra-high-order "Extreme AO" systems for exoplanet imaging.

By pushing regions of the mirror forward where the incoming light wavefront is delayed, and pulling back where the wavefront is advanced, the mirror reflects a perfectly flat, coherent wave phase toward the camera.

Laser Guide Stars (LGS): Creating Artificial Calibration Points

To measure wavefront distortion, the Wavefront Sensor needs a bright, point-like light source—a

Guide Star

—located immediately adjacent to the target object.

Because bright natural stars cover less than 1% of the night sky (creating a severe "sky coverage" limitation), astronomers create artificial point sources high in the atmosphere using

Laser Guide Stars (LGS)

.

Laser Guide Star Types

│

┌───────────────────────────┴───────────────────────────┐

▼                                                       ▼

┌─────────────────────────┐                             ┌─────────────────────────┐

│ Sodium Resonance LGS    │                             │ Rayleigh Scattering LGS │

│ Excites sodium layer at │                             │ Collides with molecules │

│ 90 km altitude.         │                             │ at 15–20 km altitude.   │

└─────────────────────────┘                             └─────────────────────────┘

1. Sodium Layer Resonance Lasers (80–105 km)

The Physics:

Micrometeorites vaporize upon entering Earth's upper atmosphere, leaving behind a thin layer of free sodium atoms in the mesosphere at an altitude of roughly

90

km

(

56

miles

).

Laser Operation:

Observatories project a high-power laser tuned precisely to the

589

nm

sodium D2 resonance line

(yellow-orange light).

Mechanism:

The laser excites the sodium atoms, causing them to fluoresce and glow. From the ground, this tiny excited patch of the mesosphere acts as an artificial guide star sitting well above the turbulent troposphere.

2. Rayleigh Scattering Lasers (15–20 km)

The Physics:

Ultraviolet or green lasers are pulsed into the lower atmosphere, scattering off atmospheric nitrogen and oxygen molecules via Rayleigh scattering.

Mechanism:

By using electronic range-gating on the wavefront sensor, astronomers capture only the scattered light returning from a specific distance (e.g.,

15

km

altitude), creating a lower-altitude artificial reference point.

Limitations and Advanced AO Techniques

While standard single-conjugate AO drastically improves resolution, it faces physical constraints:

Anisoplanatism:

Turbulence varies depending on viewing angle. A single guide star corrects light within a tiny angular patch (the

isoplanatic angle

, often just a few arcseconds wide).

Focus Anisoplanatism (Cone Effect):

Because a Laser Guide Star is created at a finite altitude (

90

km

) rather than at infinity like a real star, its light travels back in a cone shape, missing atmospheric turbulence in the outer regions of the telescope's aperture cone.

Advanced Solutions:

Multi-Conjugate Adaptive Optics (MCAO):

Projects multiple laser guide stars across a field of view and uses several deformable mirrors conjugated to different atmospheric layer heights (e.g.,

0

km

,

4

km

,

10

km

). This reconstructs a 3D tomographic map of atmospheric turbulence, achieving wide-field diffraction-limited imaging.

Extreme Adaptive Optics (ExAO):

Utilizes tens of thousands of actuators running at ultra-high speed (

>

2

kHz

) specifically to suppress scattered starlight, enabling direct imaging and spectroscopy of faint exoplanets orbiting bright host stars.

Key Technical Summary

Component

Function

Key Specification

Wavefront Sensor

Measures local phase distortions

Shack-Hartmann or Pyramid configuration

Real-Time Computer

Reconstructs wavefront and calculates shape vectors

Sub-millisecond latency (

>

1

,

000

Hz

)

Deformable Mirror

Physically compensates wavefront errors

100

to

>

4

,

000

actuators; sub-micron precision

Sodium Laser

Excites mesospheric sodium at

90

km

589

nm

wavelength;

10

–

20

W

power

Take this topic further:

Compare Adaptive Optics with Space Telescopes

Explore Extreme AO for Exoplanet Direct Imaging
