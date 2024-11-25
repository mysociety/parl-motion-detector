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
    0.1.0: Don't need to increment, first version
  datasette:
    about: Info & Downloads
    about_url: https://pages.mysociety.org/parl_motion_detector/datasets/parliamentary_motions/0_1_0
resources:
- title: Agreements
  description: dataset of agreements extracted from parliamentary debates
  custom:
    row_count: 3673
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
      example: uk.org.publicwhip/debate/2019-01-07c.121.0.8
    - name: date
      type: string
      description: date of the debate
      constraints:
        unique: false
      example: '2019-01-07'
    - name: major_heading_id
      type: string
      description: ID of the major heading (if relevant)
      constraints:
        unique: false
      example: uk.org.publicwhip/debate/2019-01-07c.137.1
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
      example: uk.org.publicwhip/debate/2019-01-07c.121.0
    - name: paragraph_pid
      type: string
      description: paragraph ID of the agreement
      constraints:
        unique: false
      example: a100.1/12
    - name: agreed_text
      type: string
      description: Text that contains the agreement
      constraints:
        unique: false
      example: '(2) That a further day not later than 5 August be allotted for the
        consideration of the following Estimate for financial year 2021-22: Foreign,
        Commonwealth and Development Office, insofar as it relates to the spending
        of the Foreign, Commonwealth and Development Office on Official Development
        Assistance and the British Council.—(David Rutley.) Question agreed to.'
    - name: motion_title
      type: string
      description: Title of the motion
      constraints:
        unique: false
      example: 20 YEARS OF DEVOLUTION
    - name: motion_gid
      type: string
      description: ID of the motion
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2019-01-07c.114.0.2
    - name: chamber
      type: string
      description: Chamber in which the agreement was made
      constraints:
        unique: false
        enum:
        - house-of-commons
      example: house-of-commons
  hash: ae2ef83fb9ac5ef5bd85ff4ffa08af2d
- title: Division Links
  description: Lookup between GID for a division and the relevant motion
  custom:
    row_count: 1290
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
      example: uk.org.publicwhip/debate/2019-01-08b.243.1
    - name: motion_gid
      type: string
      description: GID of the motion
      constraints:
        unique: true
      example: uk.org.publicwhip/debate/2019-01-08b.212.3.1
    - name: chamber
      type: string
      description: Chamber in which the motion was made
      constraints:
        unique: false
        enum:
        - house-of-commons
      example: house-of-commons
  hash: ad282a9481d69f6613b7fa9b5a050080
- title: Motions
  description: Motions extracted from parliamentary debates
  custom:
    row_count: 4963
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
      example: uk.org.publicwhip/debate/2019-01-07c.114.0.2
    - name: speech_id
      type: string
      description: ID of the speech containing the motion (or the first entry)
      constraints:
        unique: false
      example: uk.org.publicwhip/debate/2019-01-07c.114.0
    - name: date
      type: string
      description: date of the debate
      constraints:
        unique: false
      example: '2019-01-07'
    - name: motion_title
      type: string
      description: Title of the motion
      constraints:
        unique: false
      example: 18. Pensions (lifetime allowance charge and annual allowance)
    - name: motion_text
      type: string
      description: Text of the motion
      constraints:
        unique: false
      example: "After Clause 46 - Register of members: information to be included\
        \ and powers to obtain it\nQuestion put, That amendment (a) to Lords amendment\
        \ 23 be made."
    - name: chamber
      type: string
      description: Chamber in which the motion was made
      constraints:
        unique: false
        enum:
        - house-of-commons
      example: house-of-commons
  hash: dc57c5d10f9d501543f3190412fe3208
full_version: 0.1.0
permalink: /datasets/parliamentary_motions/latest
---
