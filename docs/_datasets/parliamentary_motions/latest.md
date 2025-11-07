---
name: parliamentary_motions
title: Parliamentary motions
description: "Motions and agreements extracted from parliamentary debates\n"
version: latest
licenses:
- name: CC-BY-4.0
  path: https://creativecommons.org/licenses/by/4.0/
  title: Creative Commons Attribution 4.0 International License
contributors:
- title: mySociety
  path: https://mysociety.org
  role: author
custom:
  build: parl_motion_detector.process:move_to_package
  tests:
  - test_parliamentary_motions
  dataset_order: 0
  download_options:
    gate: default
    survey: default
    header_text: default
  formats:
    csv: true
    parquet: true
    gpkg: false
    geojson: false
  is_geodata: false
  composite:
    xlsx:
      include: all
      exclude: none
      render: true
    sqlite:
      include: all
      exclude: none
      render: true
    json:
      include: all
      exclude: none
      render: true
  change_log:
    0.1.0: 'Change in data for resource(s): agreements,division-links,motions'
  datasette:
    about: Info & Downloads
    about_url: https://pages.mysociety.org/parl_motion_detector/datasets/parliamentary_motions/0_1_0
resources:
- title: Agreements
  description: dataset of agreements extracted from parliamentary debates
  custom:
    row_count: 7909
    datasette:
      about: Info & Downloads
      about_url: https://pages.mysociety.org/parl_motion_detector/datasets/parliamentary_motions/0_1_0#agreements
  path: agreements.parquet
  name: agreements
  profile: data-resource
  scheme: file
  format: parquet
  hashing: md5
  encoding: utf-8
  schema:
    fields:
    - name: gid
      type: string
      description: unique identifier for the agreement - debate gid plus paragraph
        pid
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2001-10-24.380.1.18
    - name: date
      type: string
      description: date of the debate
      constraints:
        unique: false
      example: '2001-10-24'
    - name: major_heading_id
      type: string
      description: ID of the major heading (if relevant)
      constraints:
        unique: false
      example: ''
    - name: minor_heading_id
      type: string
      description: ID of the minor heading (if relevant)
      constraints:
        unique: false
      example: ''
    - name: speech_id
      type: string
      description: ID of the speech containing the agreement
      constraints:
        unique: false
      example: uk.org.publicwhip/debate/2001-10-24.380.1
    - name: paragraph_pid
      type: string
      description: paragraph ID of the agreement
      constraints:
        unique: false
      example: .100.4/3
    - name: agreed_text
      type: string
      description: Text that contains the agreement
      constraints:
        unique: false
      example: '  Question put and agreed  to  .'
    - name: negative
      type: boolean
      description: Boolean on if the agreement is to reject the motion
      constraints:
        unique: false
        enum:
        - false
        - true
      example: 'False'
    - name: motion_title
      type: string
      description: Title of the motion
      constraints:
        unique: false
      example: ' Alternative Pathways to Primary Care'
    - name: motion_gid
      type: string
      description: ID of the motion
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2001-10-24.328.3.1
    - name: chamber
      type: string
      description: Chamber in which the agreement was made
      constraints:
        unique: false
        enum:
        - house-of-commons
        - scottish-parliament
      example: house-of-commons
  hash: c67b2cb798fde5bf222fa0786f35f177
- title: Division Links
  description: Lookup between GID for a division and the relevant motion
  custom:
    row_count: 5006
    datasette:
      about: Info & Downloads
      about_url: https://pages.mysociety.org/parl_motion_detector/datasets/parliamentary_motions/0_1_0#division-links
  path: division-links.parquet
  name: division-links
  profile: data-resource
  scheme: file
  format: parquet
  hashing: md5
  encoding: utf-8
  schema:
    fields:
    - name: division_gid
      type: string
      description: GID of the division
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2001-10-24.325.0
    - name: motion_gid
      type: string
      description: GID of the motion
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2001-10-24.321.1.1
    - name: chamber
      type: string
      description: Chamber in which the motion was made
      constraints:
        unique: false
        enum:
        - house-of-commons
        - scottish-parliament
      example: house-of-commons
  hash: 7f78df5b4bfb26e2e0c0dc99ba159613
- title: Motions
  description: Motions extracted from parliamentary debates
  custom:
    row_count: 12915
    datasette:
      about: Info & Downloads
      about_url: https://pages.mysociety.org/parl_motion_detector/datasets/parliamentary_motions/0_1_0#motions
  path: motions.parquet
  name: motions
  profile: data-resource
  scheme: file
  format: parquet
  hashing: md5
  encoding: utf-8
  schema:
    fields:
    - name: gid
      type: string
      description: unique identifier for the motion - debate gid plus paragraph pid
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2001-10-24.321.1.1
    - name: speech_id
      type: string
      description: ID of the speech containing the motion (or the first entry)
      constraints:
        unique: false
      example: uk.org.publicwhip/debate/2001-10-24.321.1
    - name: date
      type: string
      description: date of the debate
      constraints:
        unique: false
      example: '2001-10-24'
    - name: motion_title
      type: string
      description: Title of the motion
      constraints:
        unique: false
      example: ' Alternative Pathways to Primary Care'
    - name: motion_text
      type: string
      description: Text of the motion
      constraints:
        unique: false
      example: "  Question put (Standing Order No. 31(2)), That the original words\
        \ stand part of the Question.\nAmendment:\nI beg to move an amendment, to\
        \ leave out from \"House\" to the end of the Question and add:\n\"notes the\
        \ appalling fiscal deficit left by the last Government and reiterates the\
        \ urgent need to restore the nation to economic health; recognises that the\
        \ police will need to play their part in reducing that deficit; and welcomes\
        \ the Government's proposed policing reforms, which will deliver a more responsive\
        \ and efficient police service, less encumbered by bureaucracy, more accountable\
        \ to the public and, most importantly, better equipped to fight crime.\"\n\
        Original words:\nI beg to move,\nThat this House notes with concern the Government's\
        \ failure to prioritise the safety of communities by not protecting central\
        \ Government funding for the police; notes the conclusion of the Audit Commission\
        \ and HM Inspectorate of Constabulary that any budget reduction over 12 per\
        \ cent. will reduce frontline policing; pays tribute to the police and other\
        \ agencies for achieving a 43 per cent. reduction in crime, including a 42\
        \ per cent. cut in violent crime, since 1997, and for maintaining that reduction\
        \ through last year's recession; notes that public perception of anti-social\
        \ behaviour is at its lowest level since it was recorded in the British Crime\
        \ Survey of 2001-02; further notes that the previous Government set out plans\
        \ in its Policing White Paper to drive down policing costs whilst maintaining\
        \ core funding; and condemns the Government's policy of reducing police numbers,\
        \ restricting police powers and imposing elected commissioners to replace\
        \ police authorities, thus condemning the police service to unnecessary, unwelcome\
        \ and costly re-structuring at a time when their focus should be on maintaining\
        \ the fall in crime and anti-social behaviour."
    - name: chamber
      type: string
      description: Chamber in which the motion was made
      constraints:
        unique: false
        enum:
        - house-of-commons
        - scottish-parliament
      example: house-of-commons
  hash: 00dedd0e0fa5c494dc5fca723759c7d3
full_version: 0.1.0
permalink: /datasets/parliamentary_motions/latest
---
