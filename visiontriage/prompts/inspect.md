---
name: inspect
version: 1
---
Describe only what is visibly present in each image. For every image report:
the visible defect or abnormality (if any), its location, image quality
(exposure, blur, contrast), and anything that looks like a labelling mistake.
If nothing abnormal is visible, say so. Do not speculate about causes,
model behaviour, or what the image was expected to show.

Respond with JSON only:
{"observations": [{"image_id": "...", "description": "...",
"quality": "...", "confidence": 0.0}]}
