---
content_id: "1e8059d3-1c63-47f6-b0a1-9b21c96ca1c6"
title: Introduction
video_url: https://www.youtube.com/watch?v=rQYyFxf1FWw
timestamps:
  - {time: "00:00", title: Welcome}
---

In this module we build a retrieval-augmented generation system, step by step.

Read the [environment page](02-environment.md#install-the-tools) first.

![Project overview](images/diagram.png)

```embed
type: youtube
id: rQYyFxf1FWw
```

```mermaid
graph TD; A-->B;
```

A fenced block is text, so `{% include x.html %}` inside one is not Liquid:

```liquid
{% include youtube.html video_id="abc" %}
```
