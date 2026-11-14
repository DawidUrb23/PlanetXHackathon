
import math


def update_tracks(
    tracks,
    detections,
    frame_index,
    next_track_id,
    max_distance=5
):

    possible_matches = []

    # Find possible matches from the previous frame
    for track_index, track in enumerate(tracks):

        last = track["observations"][-1]

        if last["frame_index"] != frame_index - 1:
            continue

        for detection_index, detection in enumerate(detections):

            distance = math.hypot(
                last["x"] - detection["x"],
                last["y"] - detection["y"]
            )

            if distance <= max_distance:
                possible_matches.append((
                    distance,
                    track_index,
                    detection_index
                ))

    # Match closest pairs first
    possible_matches.sort()

    used_tracks = set()
    used_detections = set()

    for distance, track_index, detection_index in possible_matches:

        if track_index in used_tracks:
            continue

        if detection_index in used_detections:
            continue

        detection = detections[detection_index]

        tracks[track_index]["observations"].append({
            **detection,
            "frame_index": frame_index
        })

        used_tracks.add(track_index)
        used_detections.add(detection_index)

    # Create new tracks for unmatched detections
    for detection_index, detection in enumerate(detections):

        if detection_index in used_detections:
            continue

        tracks.append({
            "track_id": next_track_id,
            "observations": [{
                **detection,
                "frame_index": frame_index
            }]
        })

        next_track_id += 1

    return tracks, next_track_id
