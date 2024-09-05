
# parl-motion-detector

This repository is to make a motion and agreement extractor that enhances our existing transcripts.

The end goal is to:

- Extract 'Agreements' - when decisions are made without a vote.
- For Agreements and Divisions - connect to the motion or motions that are being voted on in chain.

Unsolved problems:

- We're getting titles from Parliament for divisions - we'll have to create them (automatically?) for agreements.

# Difficult/noteworthy days

- Standard opposition day motion with amendment - 2023-06-27
- Passing of net zero target (agreement on SI) - 2019-06-24
- Gaze ceasefire votes (amended motion, two agreements in a row, motion to sit in silence) - 2024-02-21
- Day with lots of divisions on amendments to be connected (and random other votes) - 2024-04-24
- Fracking Opposition Day Amendment - timetable change - complicated motion.  - 2022-10-19
- Vote on government agenda - 2024-07-23
- disagreeing with lords amendments - 2024-04-22

# How does assignment of motions to decisions and agreements work

First principle is many motions *will not be assigned to agreements/divisions* - integrity check is the other way around - does a decision get relevant motion links.

Assuming that major divisions are a hard pass - and that only motions that share the same hard pass count. 

In the ideal case, under a major division, we have one motion and one decision. This solves itself.

Where a motion either shares or is the id immediately preceding - that's the preferred candidate. 

Agreements are more likely to share an ID as we haven't seperated these off. - but you might get *several* motions and agreements in one speech.  (We should keep track of the pid at the start.)

Multiple motions may be associated with a decision - e.g. any where an amendment to the main motion succeeds. There is usually a hint (as amended).


