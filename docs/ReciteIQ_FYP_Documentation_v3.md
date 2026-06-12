**ReciteIQ: Smart Quran Recitation Alignment and Correction System**

**Submitted By**
Muhammad Abdullah Awais
Huzaifa Naseer
2023-2027

**Institute of Computer Science**
**Khwaja Fareed University of Engineering & Information Technology**
**ReciteIQ: Smart Quran Recitation Alignment and Correction System**

**Submitted to**
**Dr. Madiha Rehman**

**Institute of Computer Science**
**In partial fulfilment of the requirements**
**For the degree of**

**Bachelor's in Computer Science**

**By**
Muhammad Abdullah Awais
COSC232101006
Huzaifa Naseer
COSC232101004
2023-2027

**Khwaja Fareed University of Engineering & Information Technology**
**Rahim Yar Khan**
**2026**

**DECLARATION**

We hereby declare that this project report is based on our original work except for citations and quotations which have been duly acknowledged. We also declare that it has not been previously and concurrently submitted for any other degree or award at Khwaja Fareed University of engineering & Information Technology or other institutions.

| Reg No: | COSC232101006 | Reg No: | COSC232101004 |
| --- | --- | --- | --- |
| Name: | Muhammad Abdullah Awais | Name: | Huzaifa Naseer |
| Signature: | _________________________ | Signature: | _________________________ |
| Date: | _________________________ | Date: | _________________________ |

**APPROVAL FOR SUBMISSION**

I certify that this project report entitled ReciteIQ: Smart Quran Recitation Alignment and Correction System was prepared by Muhammad Abdullah Awais and Huzaifa Naseer has met the required standard for submission in partial fulfilment of the requirements for the award of bachelor's in computer science at Khwaja Fareed University of Engineering & Information Technology.

Approved by:

**Signature:**   _________________________

**Supervisor:   Dr. Madiha Rehman                 **

**Date:**   _________________________
**MEETING LOG**

**ACKNOWLEDGEMENT**
We would like to thank everyone who had contributed to this project. We would like to express our gratitude to our Project supervisor, Dr. Madiha Rehman for her invaluable advice, guidance, and her enormous patience throughout the development of the project.
In addition, we would also like to express our gratitude to our loving parents and friends who had helped and given us encouragement. 
**ABSTRACT**

ReciteIQ (Digital Mutashabeh Monitor) is a web-based recitation monitoring system designed to act as an automated "Sami" (listener) for a Hafiz-e-Quran. The system captures recitation audio in the browser, converts it into Arabic text using an Automatic Speech Recognition (ASR) model, and tracks the recitation against a Quran database in Uthmani script stored in PostgreSQL. At word-level granularity, the Quran text is tokenised into individual words to support precise matching and skip detection.
The core detections in this FYP scope are: (i) missed Ayah, (ii) missed word within an Ayah, and (iii) Mutashabeh jumps (switching to a similar verse/location). The comparison layer uses string-matching techniques (e.g., edit-distance/Levenshtein-style matching) to compare the live ASR text with the expected Quranic text while applying "wait and listen" logic so that normal pauses do not immediately trigger a missed-Ayah alert. The output is presented in real time through a web interface that highlights correct portions in green and detected errors/warnings in red, with an explicit warning when the system believes the reciter has switched to another Surah/Ayah due to similarity.
By combining speech processing, Natural Language Processing, and web application development, ReciteIQ addresses a clear gap in the current landscape of digital Quran tools: few solutions actively listen to a Hafiz and detect missed words/ayahs and Mutashabeh switches in real time. The system is designed to be accurate, responsive, and respectful of the Quranic text, and it is intended to complement human teachers by supporting self-paced revision and practice sessions.

##### TABLE OF CONTENTS

##### LIST OF FIGURES

*Figure ‎2-1 Tarteel	21*
*Figure ‎2-2 Quran.com	22*
*Figure ‎2-3 Ayat	22*
*Figure ‎2-4 Quran Companion	23*
*Figure ‎3-1 Project Gantt Chart	38*
*Figure ‎4-1 System Architecture (Layered View)	43*
*Figure ‎4-2 Entity Relationship Diagram	45*
*Figure ‎4-3 Use Case Diagram	47*
*Figure ‎4-4 Class Diagram	49*
*Figure ‎4-5 Activity Diagram	51*
*Figure ‎4-6 Sequence Diagram	52*
*Figure ‎4-7 Component / Deployment Diagram	53*
*Figure ‎4-8 Data Flow Diagram (Level 1)	54*

##### LIST OF TABLES

*Table ‎3.1: User Needs of System	27*
*Table ‎3.2: Functional Requirement (FR-01)	28*
*Table ‎3.3: Functional Requirement (FR-02)	29*
*Table ‎3.4: Functional Requirement (FR-03)	29*
*Table ‎3.5: Functional Requirement (FR-04)	30*
*Table ‎3.6: Functional Requirement (FR-05)	30*
*Table ‎3.7: Functional Requirement (FR-06)	31*
*Table ‎3.8: Functional Requirement (FR-07)	32*
*Table ‎3.9: Functional Requirement (FR-08)	32*
*Table ‎3.10: Functional Requirement (FR-09)	33*
*Table ‎3.11: Functional Requirement (FR-10)	34*
*Table ‎3.12: Functional Requirement (FR-11)	34*
*Table ‎3.13: Functional Requirement (FR-12)	35*
*Table ‎3.14: Need to Feature Mapping	37*

## INTRODUCTION

### Background

The Holy Quran holds a central place in the life of every Muslim and is recited daily across the world for both worship and memorisation. Accurate recitation, in terms of both pronunciation and the correct sequence of words and verses, is regarded as an essential religious obligation. Traditionally, students learn recitation in institutions such as Madaris and mosques, where a qualified teacher, commonly known as a Qari or Hafiz, listens to the recitation and corrects the learner whenever an error occurs. This method, although effective, is limited by the availability of teachers, physical distance, restricted class time, and the inability of a single teacher to provide individual attention to every student during self-study sessions.
In recent years, advancements in Artificial Intelligence (AI), speech processing, and Natural Language Processing (NLP) have made it possible to replicate, in part, the supervisory role of a human instructor through intelligent software systems. Automatic Speech Recognition (ASR) models have progressed significantly, and modern Arabic speech-to-text engines are now capable of transcribing recited Arabic audio with increasing accuracy. Parallel progress in text-alignment algorithms and digital Quran databases has opened new possibilities for building assistive technologies that can listen to a learner's recitation and provide meaningful feedback in real time.
ReciteIQ (Digital Mutashabeh Monitor) builds upon these advancements to support Hifz practice by listening to a reciter through the browser microphone, converting the Arabic speech into text, and comparing it against the original Quranic text stored in a structured Uthmani-script database. By performing word-level alignment and sequence tracking, the system detects three key issues within the FYP scope: missed words within an Ayah, missed Ayahs (skipping ahead), and jumps to similar (Mutashabeh) locations. Detected issues are highlighted on the web interface so the reciter can correct mistakes immediately.
The project is designed for the web phase in the current FYP scope, delivered through a web-based interface with a backend service implemented in Node.js and a dedicated Python-based AI engine responsible for speech transcription and alignment. A PostgreSQL database stores the structured Quran dataset, including Surahs, Ayahs, and normalised word sequences. Real-time interaction is achieved through WebSocket-based audio streaming, ensuring low latency between the reciter's input and the system's feedback. In its initial version, ReciteIQ focuses on text-level alignment and correction, which provides a strong technical foundation and a realistic scope for an undergraduate final year project, while keeping the door open for future extensions such as Tajweed analysis and phoneme-level evaluation.

### Introduction

ReciteIQ is proposed as a web-based "Sami" (listener) for Hifz revision. In the web interface, the reciter selects a Surah and starting Ayah, then begins reciting. The browser captures audio (Web Speech / browser microphone input) and streams it to the backend, where an Automatic Speech Recognition (ASR) model converts recitation into Arabic text. This text is then normalised (e.g., removal of diacritics) so that matching against the reference Uthmani script becomes consistent.
At the core of the system is a word-level alignment and tracking engine. The Quran text is tokenised into individual words, and the live recitation stream is compared against the expected word sequence using string-matching techniques (e.g., edit-distance matching). The tracking logic is pause-aware ("wait and listen"): when the reciter pauses, the system waits before raising a missed-Ayah alert. In parallel, a Mutashabeh knowledge base (a mapping of similar verses/phrases) helps the system detect when the reciter accidentally switches to a similar location; if the spoken phrase matches another Surah/Ayah better than the current position, the system flags a Mutashabeh jump warning and shows the suspected new location.
Unlike generic speech applications or static Quran readers, ReciteIQ is specifically tailored to the linguistic and structural characteristics of the Quran and to the pedagogical needs of Hifz and Nazra students. It is intended to complement, not replace, the role of a human teacher by providing instant corrective feedback during practice sessions when a teacher is not available. This chapter introduces the motivation behind the project, defines the problem it addresses, outlines its objectives, describes the intended scope, highlights its advantages, and establishes its relevance to the undergraduate Computer Science programme.

### Problem Statement

Despite the strong tradition of Quran learning across the Muslim world, the dominant mode of recitation practice is still based on one-to-one interaction between a learner and a qualified teacher. While this model produces excellent results, it suffers from several practical limitations that are becoming more evident as the number of learners grows and as learning increasingly takes place outside formal classroom hours. A teacher can only supervise a limited number of students at a time, and the attention given to each student is necessarily brief. Many learners, particularly those in remote areas, do not have regular access to a qualified instructor, and even those who do are often unable to benefit from continuous supervision during home study.
During self-study, Hifz students may unintentionally miss a word, skip an Ayah, or switch to another similar (Mutashabeh) location without realising it. These mistakes can become ingrained if they are not corrected immediately. Existing digital Quran applications are primarily focused on displaying text and playing pre-recorded recitations; they do not listen to the user and therefore cannot provide real-time, personalised correction. Generic speech-recognition solutions can transcribe Arabic audio but do not provide Quran-structure-aware tracking and do not address the specific challenge of Mutashabeh switching. A further practical challenge is that reciters naturally pause for breath; therefore, a useful system must differentiate between a genuine skip and a normal pause ("wait and listen").
There is therefore a clear need for a web-based digital "Sami" that can listen to a Hafiz's recitation, track it against an authoritative Uthmani-script Quran database at word level, and detect the three key error cases in this FYP scope: missed words, missed Ayahs (skipping ahead), and Mutashabeh jumps to similar locations. The system must provide feedback in real time and must include pause-aware logic so that normal breathing and short silences do not cause false missed-Ayah alerts.

### Objective

The principal objective of the ReciteIQ project is to design and develop an intelligent web-based system that listens to a Hafiz-e-Quran's recitation and provides accurate, real-time feedback on the correctness of the recited text. In the current FYP phase, the focus is on delivering the core functionality through a web interface while combining speech recognition, Arabic text normalisation, and sequence alignment into a single integrated solution.
**Goal of the Project:** When a Hafiz-e-Quran is reciting, the system should detect whether the reciter (i) misses any Ayah, (ii) misses any word within an Ayah, or (iii) jumps from the current recitation position to another similar (Mutashabih) place.
- To build a web-based Digital Mutashabeh Monitor that acts as an automated "Sami" (listener) for Hifz recitation.
- To capture the reciter's audio in the browser and convert it into Arabic text using an ASR model.
- To implement word-level tokenisation and sequence alignment with pause-aware ("wait and listen") logic.
- To detect (i) missed Ayahs, (ii) missed words within an Ayah, and (iii) Mutashabeh jumps to similar locations, and to show the suspected destination (Surah/Ayah) when a switch is detected.
- To provide real-time visual feedback in the web interface using clear red/green highlighting for errors and correct recitation.

### Project Scope

The scope of this FYP phase is strictly focused on building the core web-based product: the Digital Mutashabeh Monitor. The project concentrates on tracking Quran recitation against an Uthmani-script Quran database at word level and providing real-time monitoring and correction. The scope is limited to the three target detections (missed Ayah, missed word within an Ayah, and Mutashabeh jump) and the supporting workflow required to deliver these detections reliably in a browser-based application.
Workflow within scope: (1) **Input Layer**--capture the Hafiz's audio in the browser (Web Speech / microphone input); (2) **Processing Layer**--use an ASR model to generate Arabic text; (3) **Comparison Layer**--apply string-matching (e.g., Levenstein-style matching) between live text and the reference Uthmani-script Quran text; (4) **Error Detection**--detect "null"/missing matches (missed words/ayahs) and "out-of-sequence" matches (Mutashabeh jump), with pause-aware ("wait and listen") handling; (5) **Output Layer**--highlight correct recitation in green and errors/warnings in red in real time on the web interface.
Out of scope for this FYP phase: full Tajweed analysis, phoneme-level pronunciation scoring, speaker identification, multi-Qira'at support, advanced learning analytics, and any additional error categories beyond the three specified (e.g., extra-word detection or wrong-Surah detection). The focus is to deliver a clean, working web-based monitor for missed Ayah, missed word, and Mutashabeh jump detection.

### Advantages of the System

ReciteIQ offers a few practical and educational advantages for students, teachers, and institutions involved in Quran learning. By providing an always-available digital assistant that can listen, understand, and correct recitation at the word level, the system helps to make high-quality recitation practice accessible to a much wider audience than is possible through human teachers alone. The key advantages of the system are summarised below.
- Accessibility: learners can practise recitation at any time and from any location, including areas where qualified teachers are not easily available.
- Personalisation: each session is specific to the individual learner, adapting to the Surah, Ayah, and pace that they choose, and providing feedback that is directly relevant to their own performance.
- Instant feedback: errors are highlighted and reported in real time, allowing learners to correct mistakes immediately rather than repeating them until the next class.
- Consistency: the system applies the same rules and the same reference text for every user, which reduces variability in feedback and supports uniform standards of accuracy.
- Reduced teacher workload: by handling routine detection of skipped, missing, and extra words during practice, the system allows human teachers to focus on deeper areas such as Tajweed and spiritual guidance.
- Suitability for Hifz students: memorisation students benefit greatly from a system that can listen patiently for long sessions, detect slips immediately, and help them reinforce accurate retention.
- Suitability for Nazra students: beginners who are learning to read the Quran receive gentle, objective, and immediate correction that supports confidence and steady progress.
- Scalability: the client-server architecture with a dedicated AI service allows the system to support many learners concurrently without replicating specialised software on each device.
- Extensibility: the modular design leaves clear integration points for future features such as Tajweed analysis, progress tracking, and multi-language guidance.

### Relevance to the Study Program

ReciteIQ is highly relevant to the Bachelor of Science in Computer Science programme at the Institute of Computer Science, Khwaja Fareed University of Engineering and Information Technology. The project integrates and applies a broad set of competencies developed during the undergraduate curriculum, ensuring that its design and implementation constitute a substantive final year engineering effort. Several core areas of the study programme are directly exercised by the project.
- Artificial Intelligence and Machine Learning: the project relies on modern speech recognition models and on designing an intelligent alignment engine capable of handling real-world, noisy input.
- Natural Language Processing: Arabic text normalisation, tokenisation, and sequence alignment are classical NLP tasks that form the backbone of the system.
- Software Engineering: the project is built following a disciplined software process, including requirements engineering, design, implementation, and testing, using proper documentation and version control.
- Database Systems: a structured Quran dataset is stored and queried using PostgreSQL, requiring careful schema design, indexing, and query optimisation.
- Web Application Development: the client is implemented as a web-based interface, covering front-end development, user interface design, and browser-based device integration (microphone access).
- Computer Networks and Distributed Systems: communication between the mobile client and backend services is designed around WebSockets, demonstrating real-time streaming and client-server architectures.
- Human-Computer Interaction: the highlighting interface, feedback design, and overall usability of the mobile application demonstrate applied knowledge of interaction design.
By combining these diverse areas within a single coherent applied project, ReciteIQ fulfils the expectations placed on a final year undergraduate project.

### Chapter Summary

This chapter has introduced ReciteIQ, an intelligent Quran recitation alignment and correction system, and has established the motivation and context for the project. It has described the limitations of traditional Quran learning and of existing digital tools, and it has explained how a focused combination of Arabic speech-to-text, text normalisation, and word-level alignment can address these limitations. The problem statement, objectives, scope, advantages, and relevance of the project to the Computer Science study programme have all been presented to give a complete overview of the work that follows. The remaining chapters of this report will examine existing systems in more detail, present the requirements engineering process, describe the design and architecture of the system, and outline the plans for its database, development, and testing.

## EXISTING SYSTEMS

### Existing Systems

Before designing ReciteIQ it was necessary to study the landscape of existing digital Quran learning tools and generic speech-recognition applications. A variety of applications currently assist users in reading, listening to, and memorising the Quran. These existing systems can broadly be divided into three categories: traditional digital Quran readers, audio-based recitation platforms, and a small but growing group of recitation assistance and Tajweed evaluation systems. Studying these systems has provided valuable insight into what users already appreciate in digital Quran tools and, more importantly, what remains missing.
The first category, digital Quran readers, includes widely used applications and online services that display the Quran text in a readable format, often with optional translations, tafsir, and word-by-word meanings. These systems focus mainly on content presentation and rely on the user to self-assess the correctness of their recitation. The second category, audio-based recitation platforms, offers pre-recorded recitations from well-known reciters, typically with options to loop, repeat, and slow down playback. These applications help learners to listen and imitate but do not analyse the user's own voice. The third category includes emerging systems that attempt to evaluate recitation using speech recognition and, in some cases, machine learning. However, most publicly available solutions in this category are either still in early research stages, limited to specific Surahs, or focused primarily on Tajweed rules without handling the practical, high-level errors that occur during everyday practice.
A study of these systems highlights a clear market and educational gap for a tool that genuinely listens to the user, determines what is being recited, and provides text-level corrective feedback on skipped, missing, extra, jumped, and wrong-Surah errors. ReciteIQ is positioned directly into this gap and builds on the strengths of the existing categories while addressing their most important weaknesses.

### Drawbacks in Existing Systems

A careful analysis of existing digital Quran tools and speech-based educational applications reveals a consistent set of drawbacks that limit their usefulness as recitation correction systems. These drawbacks have directly informed the design decisions taken in ReciteIQ, ensuring that the proposed system concentrates its effort on the areas where users currently experience the greatest difficulty.
- Lack of active listening: most popular Quran applications are purely visual, or audio-playback based and do not listen to the user's own recitation at all.
- Absence of structural alignment: even when audio is captured, few systems perform word-level alignment between the recited text and the reference Quran text, which is essential for meaningful correction.
- Limited error categories: the handful of systems that do attempt correction are usually restricted to pronunciation scoring and ignore common high-level errors such as skipped words, missing words, jumped ayahs, or recitation from a wrong Surah.
- Weak Arabic text handling: many existing systems do not normalise diacritics and alternative character forms robustly, which causes false mismatches between correctly recited text and the reference Quran text.
- Poor real-time behaviour: some research prototypes operate in a batch manner, analysing the entire recording only after the user finishes, which prevents them from being used as live correction companions.
- Insufficient coverage: several applications support only selected Surahs or short sections of the Quran, which makes them unsuitable for serious Hifz or Nazra study.
- Limited platform support: several promising solutions exist only on a single platform, or only as web tools, and are not well suited to mobile-first learners.
- Closed and inflexible architectures: many solutions are built as monolithic applications that do not cleanly separate speech recognition, alignment logic, and presentation, which makes it difficult to improve or extend individual components.

### Examples of Existing Systems

To ground the analysis in concrete examples, five representative existing systems have been examined in detail. These systems were selected because they are widely used by Quran learners, are frequently cited in related discussions, or are closely related to the functionality envisaged for ReciteIQ. They span four broad categories: AI-powered recitation assistants, digital Quran readers, audio-centric recitation platforms, memorisation trackers, and generic Arabic speech-recognition services. The following subsections describe each system, its strengths, and its limitations relative to the goals of ReciteIQ.

#### Tarteel AI

Tarteel AI is one of the closest commercial efforts to ReciteIQ. It offers a mobile and web-based Quran companion that listens to a reciter through the device microphone, transcribes the recitation using a custom Arabic speech-recognition model, and visually tracks the position in the Mushaf in real time. Tarteel AI also provides memorisation tests and progress dashboards. However, much of its advanced functionality is gated behind a paid subscription, and its error feedback is largely limited to position tracking rather than the structured Mutashabeh-jump and missed-Ayah detection that ReciteIQ targets.

*Figure ‎2-1 Tarteel*

#### Quran.com

Quran.com is one of the most widely used digital Quran reading platforms in the world. It presents the Uthmani-script text together with multiple translations, tafsir, word-by-word meanings, and audio recitations from well-known Qaris. Its strengths lie in clean presentation, accessibility, and breadth of reference material. However, Quran.com is fundamentally a reading and listening tool: it does not capture the user's voice and offers no mechanism for evaluating recitation correctness, which is the core capability that ReciteIQ aims to provide.

*Figure ‎2-2 Quran.com*

#### Ayat (King Saud University Quran Project)

Ayat is a popular Quran application developed under the King Saud University Quran research initiative. It focuses on high-quality audio recitations from a wide range of reciters, with features for verse repetition, looping, and synchronised text highlighting during playback. The application is excellent for imitation-based learning, in which the user listens to a reference recitation and tries to match it. Like other audio-centric tools, Ayat does not analyse the user's own recitation and therefore cannot detect missed words, missed Ayahs, or jumps to similar verses.

*Figure ‎2-3 Ayat*

#### Quran Companion

Quran Companion is a memorisation-focused application designed to support Hifz students through structured plans, daily revision schedules, and self-administered tests. The system tracks which Surahs or pages a student has completed and provides reminders to help maintain a consistent memorisation routine. While it is valuable as a planning and tracking tool, it does not actively listen to the recitation: progress is self-reported by the user. ReciteIQ complements such workflows by providing the active listening and correction layer that Quran Companion-style tools leave to the learner.

*Figure ‎2-4 Quran Companion*

### Need to Replace Existing Systems

The term "replace" should not be understood here as a claim that existing tools have no value. On the contrary, many of them perform their intended purpose well and will continue to be used alongside ReciteIQ. What is being replaced is the specific workflow in which a learner must rely on their own self-assessment, or on post-session human review, to discover recitation errors. This workflow has three major weaknesses: it is slow, it depends on the learner's ability to notice their own mistakes, and it does not scale to long memorisation sessions or to remote learners without regular teacher access.
ReciteIQ proposes to replace the traditional self-assessment workflow with a web-based real-time loop in which the system listens, transcribes, aligns, and responds while the Hafiz is reciting. The user retains full control, but the system takes on the task of tracking position and detecting the three in-scope issues (missed word, missed Ayah, Mutashabeh jump) with pause-aware handling.
Furthermore, there is a strong need for a system that is deliberately designed around the errors that most commonly confuse Hifz students during revision: missing a word, skipping an Ayah, and switching to a similar (Mutashabeh) location. Building the matching and tracking logic around these cases produces more relevant feedback and a more useful tool for the learner within the limited FYP scope.

### Chapter Summary

This chapter has surveyed the existing landscape of digital Quran learning and speech-based educational tools and has examined their strengths and weaknesses. It has shown that although a rich ecosystem of reading and listening applications exists, there is a clear gap in active recitation correction, particularly at the text level. The drawbacks of current tools, including the absence of listening, poor error categorisation, weak Arabic text handling, and lack of real-time feedback, have been identified. A set of representative examples has been discussed to illustrate these drawbacks in concrete terms, and the argument has been made for replacing the current self-assessment workflow with an intelligent, real-time recitation correction loop. The next chapter will build on this analysis by formally engineering the requirements of ReciteIQ as an applied response to these gaps.

## REQUIREMENT ENGINEERING

### Proposed System

The proposed system, ReciteIQ (Digital Mutashabeh Monitor), is a web-based solution that listens to a Hafiz's recitation and provides real-time feedback by tracking the recitation against an authoritative Quran database in Uthmani script. The system follows a browser-to-server workflow: the browser captures microphone audio, an ASR model converts the audio into Arabic text, and a comparison engine applies string-matching and sequence alignment at word level to detect missed words, missed Ayahs, and Mutashabeh jumps. The output is returned to the web interface where correct portions are highlighted in green and detected issues are highlighted in red.
The user starts a session in the web interface by selecting a Surah and starting Ayah. Audio is captured through the browser microphone and streamed to the backend over a WebSocket connection. The backend invokes an ASR model to generate Arabic text, normalises the transcript, and compares the live tokens with the reference word sequence using edit-distance style matching. Missed-word and missed-Ayah cases are detected as missing/null matches, while Mutashabeh switching is detected using out-of-sequence matches supported by a Mutashabeh knowledge base (a mapping of similar verses/phrases). When a switch is detected, the system warns the user and reports the suspected destination (Surah and Ayah).
The proposed system is designed as a modular web architecture so that the ASR component, the text normalisation and matching logic, the Mutashabeh knowledge base, and the web user interface can be improved independently. This separation supports iterative development during the FYP timeline and keeps the implementation aligned with the limited scope of the Digital Mutashabeh Monitor.

### Understanding the System

Before moving to a formal list of requirements, it is important to describe the system in the broader context of its users, stakeholders, domain, and needs. This subsection therefore clarifies who will interact with ReciteIQ, who has an interest in its success, which knowledge domains are relevant to its design, and what specific needs it is expected to satisfy.

#### User Involvement

The primary users of ReciteIQ are Quran learners, including Hifz students engaged in memorisation, Nazra students learning to read the Quran, and general users who wish to practise and improve their recitation. Users interact with the system through a web-based interface. A typical user flow involves opening the web application, selecting a Surah and a starting Ayah, starting a recitation session, reciting aloud while observing on-screen feedback, and finally stopping the session to review which words were recognised correctly and which caused errors. Users are not expected to have any technical background, so the user experience has been designed around familiar web patterns and clearly visible highlights, with minimal configuration required to begin practising.
User involvement has also played a role during the requirement engineering phase itself. Informal discussions with Hifz and Nazra students, as well as with experienced teachers, have been used to understand how they currently practise, what kinds of mistakes occur most often, and what form of feedback they find most useful. These insights have guided the choice of error categories, the design of thhighlighting interface, and the decision to focus on text-level correction rather than on Tajweed or phoneme-level analysis in the initial version.

#### Stakeholders

A stakeholder is any individual or group who is directly or indirectly affected by the system. In the context of ReciteIQ, the stakeholder landscape extends beyond the immediate user group to include educational institutions and supervisory bodies. Understanding these stakeholders is important for setting appropriate design priorities and for ensuring that the final system is seen as trustworthy and respectful of the subject matter.
- User (Hafiz / Hifz student): uses the web application to recite and receive real-time feedback.
- Supervisor / Evaluator: reviews progress and assesses the system against FYP requirements.
- Development Team: designs, implements, tests, and documents the system.

#### Domain

The domain of ReciteIQ spans several overlapping technical and subject-matter areas. From a technical perspective, the project belongs to the fields of Artificial Intelligence, speech processing, Natural Language Processing, mobile application development, and educational technology. The AI and speech processing components concern the use of Automatic Speech Recognition to convert Arabic audio into text and the use of sequence-alignment techniques to compare the recited text against the reference Quran. The NLP aspect focuses on Arabic text normalisation and tokenisation, while the mobile and educational technology aspects concern how the system is delivered and used by learners.
From a subject-matter perspective, the domain is that of Quran recitation and learning. This places specific constraints on the system. The reference Quran text must be stored and handled with the highest level of accuracy. The feedback provided to the user must be precise and must not give misleading impressions of correctness or error. Respect for the subject matter is reflected in the care taken to use authoritative Quran text sources and in the way that error highlights are designed to be informative without being intrusive or irreverent.

#### Needs of System

The needs of the system, viewed from the users' perspective, translate into a compact set of high-level capabilities that ReciteIQ must offer. These needs are summarised in the table below and are subsequently refined into detailed functional requirements.
*Table ‎3.1: User Needs of System*

| SR # | Needs | Need ID |
| --- | --- | --- |
| 1 | The system shall capture the reciter's audio in the browser and convert it into Arabic text using an ASR model. | N-01 |
| 2 | The system shall track the recitation at word level with pause-aware ("wait and listen") sequence alignment. | N-02 |
| 3 | The system shall detect missed Ayahs, missed words, and Mutashabeh jumps (switching to a similar location) during recitation. | N-03 |
| 4 | The system shall provide real-time web UI feedback using red/green highlighting and warnings showing the suspected destination Surah/Ayah in case of Mutashabeh switching. | N-04 |

### Requirement Specification

The requirement engineering process translates the high-level needs of the system into a formal, structured set of functional and non-functional requirements. Each functional requirement is documented using a standard template that captures its name, description, inputs, outputs, and pre- and post-conditions. Non-functional requirements describe the quality attributes that the system must satisfy, such as performance, reliability, and usability. Together, these requirements form the baseline against which the design, implementation, and testing of ReciteIQ are evaluated.

#### Functional Requirements

The functional requirements of ReciteIQ describe the observable behaviour of the system under specified inputs. They are derived directly from the user needs listed in Table 3.1 and have been refined through analysis of recitation practice workflows. A representative example is shown in Table 3.2, and the complete set of functional requirements is enumerated in the bulleted list that follows.
*Table ‎3.2: Functional Requirement (FR-01)*

| Functional Requirement ID | FR-01 |
| --- | --- |
| Name | Microphone Access and Permissions |
| Description | The system shall request, obtain, and manage browser microphone permissions so that the Hafiz's recitation audio can be captured reliably for real-time processing. |
| Input | User action to start a recitation session and the browser's microphone permission prompt/response. |
| Output | An active microphone audio stream (or a clear permission error message) available to the audio capture/streaming layer. |
| Precondition | The user has opened the web application in a supported browser and initiated a recitation session. |
| Postcondition | Microphone access is granted and the system begins capturing audio; otherwise, the user is informed that recitation cannot proceed without permission. |

*Table ‎3.3: Functional Requirement (FR-02)*

| Functional Requirement ID | FR-02 |
| --- | --- |
| Name | Real-Time Arabic ASR Transcription |
| Description | The system shall convert the live recitation audio stream into incremental Arabic text in near real time using an ASR model suitable for Quranic Arabic so that the transcript can be compared continuously against the Quran database. |
| Input | Streaming audio chunks captured from the browser microphone during a recitation session. |
| Output | Timestamped Arabic transcript segments (tokens/phrases) for downstream normalisation and alignment. |
| Precondition | Microphone permission has been granted (FR-01) and an ASR service/model is available and reachable. |
| Postcondition | The system continuously produces Arabic transcript output for the active session and forwards it to the text normalisation step (FR-03). |

*Table ‎3.4: Functional Requirement (FR-03)*

| Functional Requirement ID | FR-03 |
| --- | --- |
| Name | Arabic Text Normalisation (Diacritics Cleaning) |
| Description | The system shall normalise the Arabic ASR transcript by removing diacritics (harakat) and harmonising common character variants so that matching against the Uthmani-script reference text is consistent and less sensitive to ASR variability. |
| Input | Arabic transcript segments produced by the ASR component (FR-02). |
| Output | A normalised, diacritic-free Arabic text stream suitable for tokenisation and sequence alignment. |
| Precondition | Arabic transcript output is available from FR-02 and the normalisation ruleset is configured. |
| Postcondition | The normalised transcript is forwarded to the Surah/Ayah context and alignment engine to support tracking and error detection. |

*Table ‎3.5: Functional Requirement (FR-04)*

| Functional Requirement ID | FR-04 |
| --- | --- |
| Name | Surah/Ayah Selection Menu |
| Description | The system shall provide a web-based selection interface that allows the user to choose a Surah and a starting Ayah, creating the session context used by the alignment engine for tracking and error detection. |
| Input | User selection of Surah and starting Ayah through the web interface. |
| Output | Session context containing Surah ID, Ayah number, and the corresponding reference word sequence loaded from the Quran database. |
| Precondition | The web application is accessible, and the Quran database is available for retrieving Surah/Ayah reference text. |
| Postcondition | The system is ready to start capturing audio and aligning the recitation against the selected Surah/Ayah context. |

*Table ‎3.6: Functional Requirement (FR-05)*

| Functional Requirement ID | FR-05 |
| --- | --- |
| Name | Real-Time Sequence Alignment Engine |
| Description | The system shall align the normalised live transcript against the expected word sequence of the selected Surah/Ayah in real time using string-matching techniques (e.g., Levenstein-style alignment) and maintain the current recitation position. |
| Input | Normalised transcript tokens (FR-03) and the reference word sequence for the active Surah/Ayah (FR-04). |
| Output | An alignment result containing matched/missing/out-of-sequence tokens and the current position (Surah, Ayah, word index). |
| Precondition | An active session exists with selected Surah/Ayah and reference text loaded, and the ASR/normalisation pipeline is producing tokens. |
| Postcondition | Alignment output is available to the detection modules (FR-06 to FR-08) and the UI highlighting layer (FR-09). |

*Table ‎3.7: Functional Requirement (FR-06)*

| Functional Requirement ID | FR-06 |
| --- | --- |
| Name | Word-Level Skip (Missed Word) Detection |
| Description | The system shall detect missed words within the current Ayah by identifying expected reference tokens that remain unmatched during alignment and marking their positions as skipped/missed. |
| Input | Alignment result and current position from the alignment engine (FR-05). |
| Output | A list of missed-word indicators (word indices and optionally word text) for the active Ayah, suitable for UI highlighting and logging. |
| Precondition | The alignment engine is active (FR-05), and the system has an expected word sequence for the current Ayah. |
| Postcondition | Missed-word events are produced and forwarded to the UI highlighting and summary modules. |

*Table ‎3.8: Functional Requirement (FR-07)*

| Functional Requirement ID | FR-07 |
| --- | --- |
| Name | Ayah-Level Skip (Missed Ayah) Detection |
| Description | The system shall detect when the reciter skips an Ayah by comparing the expected next Ayah (n+1) to the observed alignment position and triggering a missed-Ayah event if the reciter proceeds to a later Ayah (e.g., n+2), while respecting pause-aware ("wait and listen") timing rules. |
| Input | Continuous alignment positions from FR-05 and session timing/pause information from the audio stream. |
| Output | A missed-Ayah alert indicating which Ayah was expected and which Ayah the reciter appears to have moved to. |
| Precondition | The system is tracking a valid current Ayah position, and the next expected Ayah is known in the selected Surah context. |
| Postcondition | Missed-Ayah events are issued for UI warning/highlighting and for inclusion in the post-session summary. |

*Table ‎3.9: Functional Requirement (FR-08)*

| Functional Requirement ID | FR-08 |
| --- | --- |
| Name | Mutashabeh (Similar Verse) Jump Detection |
| Description | The system shall detect when the reciter switches to a similar (Mutashabeh) location by comparing the best match for the currently spoken phrase across candidate Mutashabeh locations and raising a jump event if an alternative Surah/Ayah provides a stronger match than the current tracked position. |
| Input | Recent normalised transcript tokens (FR-03), alignment state (FR-05), and a Mutashabeh knowledge base (list/index of similar phrases and their Surah/Ayah locations). |
| Output | A Mutashabeh jump event including the suspected destination Surah and Ayah, plus a confidence/score if available. |
| Precondition | The Mutashabeh dataset/index is available, and the system has an active current position estimate from alignment. |
| Postcondition | A jump warning is generated for the UI (FR-10) and recorded for post-session reporting (FR-12). |

*Table ‎3.10: Functional Requirement (FR-09)*

| Functional Requirement ID | FR-09 |
| --- | --- |
| Name | Real-Time UI Text Highlighting (Red/Green) |
| Description | The system shall highlight the reference Quran text in the web interface in real time, showing correctly matched parts in green and detected missing/skipped parts in red based on alignment and detection outputs. |
| Input | Alignment results (FR-05) and missed word/Ayah events (FR-06, FR-07), streamed to the web client (e.g., via WebSocket). |
| Output | Updated on-screen rendering of the Surah/Ayah text with colour-coded highlighting for the current session. |
| Precondition | The web client has loaded the reference Surah/Ayah text and is connected to the backend for real-time updates. |
| Postcondition | The user can visually identify correct and incorrect parts during recitation and adjust immediately. |

*Table ‎3.11: Functional Requirement (FR-10)*

| Functional Requirement ID | FR-10 |
| --- | --- |
| Name | Jump Warning and Location Notification |
| Description | When a Mutashabeh jump is detected, the system shall display a clear warning message and notify the user of the suspected destination Surah and Ayah so that the reciter can return to the correct location. |
| Input | Mutashabeh jump events from FR-08, including suspected destination details and confidence/score if available. |
| Output | On-screen warning/notification showing the suspected Surah and Ayah destination, optionally with a short corrective instruction. |
| Precondition | The UI is connected for real-time updates, and a valid Mutashabeh detection event has been produced by FR-08. |
| Postcondition | The user is informed of the suspected jump destination during the session, and the warning is recorded for summary reporting. |

*Table ‎3.12: Functional Requirement (FR-11)*

| Functional Requirement ID | FR-11 |
| --- | --- |
| Name | Recitation Session Control (Pause/Resume) |
| Description | The system shall allow the user to pause and resume a recitation session from the web interface, ensuring that audio capture, ASR processing, and alignment state are paused/resumed without losing the current recitation position. |
| Input | User actions on session controls (Pause/Resume) in the web UI. |
| Output | Session state updates (active/paused) reflected in the UI and backend session context, with alignment state preserved. |
| Precondition | A recitation session has been started, and the system has an established session context (selected Surah/Ayah and current position). |
| Postcondition | When resumed, the system continues from the last known position and continues detection/highlighting without resetting the session. |

*Table ‎3.13: Functional Requirement (FR-12)*

| Functional Requirement ID | FR-12 |
| --- | --- |
| Name | Post-Session Error Summary and History |
| Description | After the session ends, the system shall generate a summary of detected issues (missed words, missed Ayahs, Mutashabeh jumps) and optionally store a session history so the user can review performance. |
| Input | Logged events from FR-06 (missed words), FR-07 (missed Ayahs), FR-08/FR-10 (Mutashabeh jumps), and session metadata (time, Surah/Ayah range). |
| Output | A session summary view/report and (if enabled) a saved record for later review in the web application. |
| Precondition | A recitation session has been completed or stopped, and detection events have been collected during the session. |
| Postcondition | The user can review errors after recitation, and the report can support further analysis/testing in later project stages. |

#### Non-Functional Requirements

The non-functional requirements describe quality attributes that the system must satisfy. These requirements complement the functional requirements by ensuring that the system behaves well under realistic operating conditions and delivers a consistently acceptable experience to its users.
- **Performance:** Real-time feedback shall appear within a few seconds of recitation to maintain natural recitation flow and timely correction.
- **Accuracy:** The engine shall accurately track the recitation and detect correct segments, missed words/Ayahs, and Mutashabeh jumps under typical usage conditions.
- **Usability:** The web interface shall be intuitive for non-technical learners, with clear highlighting and minimal cognitive load during recitation.
- **Reliability:** The system shall handle temporary network interruptions gracefully without losing session progress or the current recitation position.
- **Scalability:** The backend shall support concurrent users by scaling services (e.g., API gateway and AI service) independently without major performance degradation.
- **Maintainability:** The codebase shall remain modular so that future updates (e.g., replacing the ASR model or improving matching algorithms) can be implemented with minimal impact on other components.
- **Security:** Recitation audio and transcripts shall be protected in transit using TLS, and data retention shall be minimised to what is necessary for delivering feedback.
- **Portability:** The web client shall be compatible with modern browsers and operate consistently across common desktop and mobile platforms.
- **Respectfulness:** The user interface and stored reference text shall use authoritative Quranic scripts and follow respectful Islamic typography conventions.

#### Requirements Baseline

The requirements baseline for ReciteIQ consists of the set of functional and non-functional requirements listed above, together with the user needs in Table 3.1. This baseline represents the agreed scope of work for the final year project and has been reviewed with the project supervisor. Any change to the baseline after this point requires a controlled change request, in which the impact on design, implementation, and evaluation is assessed before approval. This disciplined approach ensures that the scope of the project remains stable and that all design and implementation work can be traced back to an approved requirement.

#### Need to Feature Mapping

The table below maps the four user needs to the four functional requirements defined for the Digital Mutashabeh Monitor.
*Table ‎3.14: Need to Feature Mapping*

| FR \ Need | N-01 | N-02 | N-03 | N-04 |
| --- | --- | --- | --- | --- |
| FR-01 | ✓ | ✗ | ✗ | ✗ |
| FR-02 | ✓ | ✗ | ✗ | ✗ |
| FR-03 | ✗ | ✓ | ✗ | ✗ |
| FR-04 | ✗ | ✗ | ✗ | ✗ |
| FR-05 | ✗ | ✓ | ✓ | ✗ |
| FR-06 | ✗ | ✗ | ✓ | ✓ |
| FR-07 | ✗ | ✗ | ✓ | ✓ |
| FR-08 | ✗ | ✗ | ✓ | ✓ |
| FR-09 | ✗ | ✗ | ✗ | ✓ |
| FR-10 | ✗ | ✗ | ✓ | ✓ |
| FR-11 | ✗ | ✓ | ✗ | ✓ |
| FR-12 | ✗ | ✗ | ✓ | ✓ |

### Gantt Chart

The project schedule for this FYP phase spans approximately five months, from the start of January 2026 to the end of May 2026, and is organised around six task groups: Planning, Requirements, Design, Implementation, Testing, and Documentation. The schedule has been planned to follow the Iterative and Incremental software process model adopted in Chapter 4: early iterations focus on requirement and design artefacts, middle iterations deliver the core implementation modules (Quran data pipeline, ASR integration, word-level alignment engine, WebSocket backend, and web client), and the final iterations consolidate the system through integration testing, supervisor reviews, and documentation. Implementation tasks are deliberately overlapped where their inputs and outputs allow parallel work, and the documentation track runs continuously alongside the technical work so that each chapter is finalised soon after the matching artefact is produced. The Gantt chart below shows the resulting task durations, dependencies, and milestone alignment in calendar form.

*Figure ‎3-1 Project Gantt Chart*

### Hurdles in Optimizing the Current System

Even with a carefully scoped design, several technical and practical hurdles must be acknowledged when optimising a system such as ReciteIQ. Arabic speech recognition, especially for recitation that follows Tajweed-oriented pronunciation, is more challenging than general conversational Arabic. ASR engines may occasionally produce incorrect transcriptions, particularly when recordings contain background noise or when learners pause frequently. The alignment engine must therefore be designed to tolerate reasonable levels of recognition noise and still report meaningful feedback.
A second hurdle is real-time performance. Streaming audio from a mobile device, performing speech recognition on the server, executing the alignment algorithm, and streaming the results back to the client must all happen fast enough to feel responsive. Careful selection of ASR models, appropriate audio chunk sizes, efficient WebSocket usage, and well-tuned database queries are all required to keep latency within acceptable bounds. A third hurdle is the preparation of the Quran dataset. Because the system depends on accurate, authoritative text, the dataset must be sourced and verified carefully, and the normalisation rules must be implemented with sufficient coverage of Arabic character variations. A fourth hurdle involves balancing scope and ambition: while it would be attractive to include full Tajweed analysis or multi-Qira'at support, the project must remain feasible within the time available, which means explicitly deferring such features to future work. Finally, designing the user interface so that feedback is helpful rather than overwhelming requires deliberate iteration and testing with real learners.

### Chapter Summary

This chapter has presented the requirement engineering work performed for ReciteIQ. It has introduced the proposed system and its architectural context, examined user involvement, stakeholders, and the project domain, and identified the core needs of the system in the form of Table 3.1. On this foundation, it has defined a concrete set of functional and non-functional requirements, illustrated with the detailed example given in Table 3.2, and has described the requirements baseline and the need-to-feature mapping that binds requirements to system features. The chapter has concluded with a summary of the project schedule and an honest assessment of the hurdles that must be overcome in order to optimise the current system. The next chapter will build on this requirement baseline by describing the software process model, methodology, and design diagrams of the system.

## DESIGN

### Software Process Model

The software process model selected for the ReciteIQ project is an Iterative and Incremental model, with elements of Agile practice in the form of short review cycles and regular supervisor feedback. This model was chosen in preference to a strict Waterfall approach because the project combines multiple technologies -- mobile development, real-time audio streaming, speech recognition, and sequence alignment -- whose interactions cannot be fully understood or finalised in a single upfront design pass. An iterative process allows each component to be prototyped, evaluated, and refined, with progressive integration leading to a stable final system.
In practice, the project has been organised into a sequence of iterations, each of which delivers a working slice of functionality. Early iterations focus on isolated components, such as an offline speech-to-text prototype or a basic alignment algorithm that operates on fixed text. Later iterations integrate these components with the mobile client and the backend, and introduce real-time behaviour. The final iterations concentrate on usability refinement, performance tuning, and comprehensive testing. At the end of each iteration, the outcomes are reviewed against the baseline requirements, any deviations are analysed, and the plan for the next iteration is adjusted accordingly.

#### Benefits of Selected Model

The Iterative and Incremental model offers a number of concrete benefits for a project with the characteristics of ReciteIQ.
- Early risk reduction: the most technically uncertain areas, such as Arabic speech recognition and word-level alignment, are tackled in early iterations, which reduces the risk of discovering fundamental obstacles late in the project.
- Continuous integration: because each iteration produces a working slice of the system, integration issues are identified and resolved incrementally rather than in a single high-risk phase at the end.
- Responsive to feedback: supervisor and user feedback can be incorporated between iterations, which keeps the system aligned with stakeholder expectations without requiring large late-stage redesigns.
- Manageable complexity: the overall complexity of the project is divided into small, manageable increments, which makes the workload more predictable for a small student team.
- Clear progress tracking: working deliverables at the end of each iteration provide concrete, demonstrable evidence of progress, which is especially valuable during reviews and evaluations.

#### Limitations of Selected Model

While the Iterative and Incremental model is well suited to ReciteIQ, it is not without limitations. These limitations have been explicitly acknowledged so that they can be managed throughout the project life cycle.
- Need for disciplined planning: frequent iterations require careful planning, otherwise the team may drift into reactive short-term development without a clear long-term direction.
- Risk of architectural drift: early prototypes may compromise on architectural cleanliness; without regular refactoring, the accumulated technical debt can slow later iterations.
- Scope management pressure: the flexibility of the model can invite continuous scope expansion, which must be resisted in order to meet the fixed academic deadlines of the final year project.
- Testing overhead: as each iteration adds functionality, regression testing workload increases, which requires a robust test strategy from an early stage.
- Coordination demand: frequent integrations require strong coordination between the two developers responsible for the mobile, backend, and AI components of the system.

### System Design

The design of ReciteIQ describes how the requirements established in the previous chapter are to be realised as concrete software components. The design is presented in several complementary views. First, the methodology of the proposed system is described, including the high-level processing pipeline. Then the entity relationship structure of the database is introduced, followed by a set of UML diagrams that model the static and dynamic behaviour of the system.

#### Methodology of the Proposed System

The methodology of ReciteIQ is organised around a clear end-to-end processing pipeline that transforms raw recitation audio into structured feedback. The pipeline is conceptually linear, but each stage has been designed to handle error conditions and to feedback information to the next stage in a robust manner. The stages are as follows.
- Session Initialisation: the user selects a Surah and starting Ayah in the web interface, and the client requests the corresponding reference text from the backend through an API endpoint.
- Audio Capture and Streaming: the web client captures microphone audio (browser microphone input) in short chunks and streams them over a WebSocket connection to the backend, tagged with the active session identifier.
- Speech Recognition: the AI service receives each audio chunk and invokes an Arabic speech-to-text engine to produce an incremental transcription.
- Text Normalisation: the raw transcription passes through an Arabic normalisation module that removes diacritics and harmonises character forms, producing a canonical token stream.
- Alignment and Error Classification: the alignment engine compares the canonical recited tokens with the expected token sequence of the selected Surah and Ayah, classifying outcomes such as missing words, missing Ayahs, and jumps to similar (Mutashabih) locations.
- Feedback Delivery: the classification output is streamed back to the web client through the same WebSocket connection, where it drives the highlighting interface in real time.
- Session Termination and Summary: when the user ends the session, the backend assembles a summary that includes recognised and missed items, which is presented to the user through the web interface.

*Figure ‎4-1 System Architecture (Layered View)*

#### Entity Relationship Diagram

The Entity Relationship Diagram (ERD) captures the core data entities maintained by ReciteIQ and the relationships between them. The primary entities include Surah, Ayah, Word, User, Session, and Error. Each Surah contains many Ayahs, and each Ayah contains a sequence of Words. A User can create multiple Sessions, where each Session is tied to a specific Surah and a starting Ayah. During a Session, any number of Errors can be recorded, and each Error references the specific Ayah and Word for which it occurred and carries a type such as skipped, missing, extra, jumped, or wrong-Surah.
This structure supports the core operations of the system with clear semantics. Alignment queries can navigate efficiently from a Surah and Ayah to the ordered sequence of Words that must be matched. Session-level analytics can be produced simply by aggregating Errors grouped by Session and by type. The ERD is designed to be extensible: future entities such as progress tracking per Surah, per-user recitation goals, or Tajweed observations can be attached to User and Session without disrupting the existing structure.

*Figure ‎4-2 Entity Relationship Diagram*

#### UML Diagrams

The dynamic and structural aspects of the system are further elaborated through a set of UML diagrams. Together, these diagrams provide a complete picture of how users interact with the system, how classes are organised internally, how activities flow during a recitation session, how messages are exchanged between components, and how the system is decomposed at the component level.

##### Use Case Diagram of the System

The Use Case Diagram identifies the main external actors of ReciteIQ and the services that the system provides to them. The primary actor is the User (Hafiz/Hifz student), who opens the web application, selects a Surah and Ayah, performs a recitation session, and reviews feedback. A secondary actor is the Administrator/Developer (for FYP setup) who maintains the Quran dataset and Mutashabeh mapping and manages the backend deployment. The main use cases include Select Surah and Ayah, Start Recitation Session, Stream Recitation Audio, Receive Real-Time Feedback, View Session Summary, and Manage Dataset. Supporting use cases such as handling network interruptions are included where appropriate.

*Figure ‎4-3 Use Case Diagram*

##### Class Diagram of the System

The Class Diagram captures the key classes of the software and the relationships between them. Representative classes include SurahSelector, RecitationSession, AudioStreamer, and FeedbackView on the client side; SessionController, WebSocketGateway, and UserService in the Node.js layer; and TranscriptionEngine, TextNormaliser, AlignmentEngine, and ErrorClassifier within the Python AI service. The data layer is represented by entity classes such as Surah, Ayah, Word, Session, and Error. Associations capture the relationships between these classes: for example, a RecitationSession contains a reference to a Surah and an AudioStreamer, and the AlignmentEngine uses both the TextNormaliser and the Surah's ordered Word sequence to produce ErrorClassifier outputs. Methods on each class reflect the responsibilities identified during the design phase, including session control, streaming, normalisation, alignment, and classification.

*Figure ‎4-4 Class Diagram*

##### Activity Diagram of the System

The Activity Diagram models the end-to-end flow of a typical recitation session. The flow begins when the learner launches the application and selects a Surah and starting Ayah. The activity diverges as soon as the session starts: one branch handles continuous audio capture and streaming, while another handles the display of feedback as it arrives. A decision node in the diagram represents the logic that determines whether each recitation unit is classified as correct, missing, skipped, extra, or jumped, and merges the results back into the main flow. The diagram also models error-handling paths, such as the response to network interruption or to severe ASR failures and terminates with the generation of a session summary when the learner chooses to stop the session.

*Figure ‎4-5 Activity Diagram*

##### Sequence Diagram of the System

The Sequence Diagram illustrates the ordered exchange of messages between the main components of the system during a single recitation iteration. The User interacts with the Web Client, which sends a session-initialisation request to the Node.js backend. The backend retrieves the relevant Surah and Ayah data from the database and opens a WebSocket channel. The Web Client then streams audio chunks to the backend, which forwards them to the AI Service. The AI Service invokes the ASR model, runs normalisation and alignment, performs error detection (missed word/Ayah and Mutashabeh switch), and returns the classification to the backend. The backend pushes the results back through the WebSocket to the Web Client, which updates the real-time highlighting interface. The sequence repeats for each audio chunk until the user ends the session.

*Figure ‎4-6 Sequence Diagram*

##### Component Diagram of the System

The Component Diagram provides an architectural view of ReciteIQ at the level of deployable units. The key components are the Web Client (browser-based interface), the Node.js Backend (responsible for API endpoints and WebSocket management), the Python AI Service (responsible for speech recognition, normalisation, matching, and Mutashabeh detection), the PostgreSQL Database (storing the Uthmani-script Quran dataset and Mutashabeh mapping), and external ASR engines (e.g., Whisper). Interfaces between components are described explicitly: HTTPS/REST and WebSocket between the Web Client and the Node.js Backend, internal HTTP calls between the Backend and the AI Service, SQL queries between the Backend and PostgreSQL, and API calls between the AI Service and the ASR engine.

*Figure ‎4-7 Component / Deployment Diagram*

*Figure ‎4-8 Data Flow Diagram (Level 1)*

### Chapter Summary

This chapter has presented the design of ReciteIQ in depth. It has justified the choice of an Iterative and Incremental software process model, identifying its benefits and limitations in the context of the project. It has explained the methodology of the proposed system in the form of a clear processing pipeline and a layered architecture, and it has introduced the entity relationship diagram that underpins the database. It has also described the set of UML diagrams, including Use Case, Class, Activity, Sequence, and Component diagrams, which together capture the structural and dynamic behaviour of the system. Taken together, these design artefacts translate the requirements baseline established in Chapter 3 into a concrete blueprint that can guide the implementation, database construction, and testing work to be presented in the later chapters of this report.
