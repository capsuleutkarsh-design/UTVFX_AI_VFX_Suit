"""Solve decisions from the Automated Tracker (core/workers.py): adopting registered frames, frame ranges."""


# How much worse the solve is allowed to get in exchange for more frames, and
# the point past which a mean reprojection error is bad regardless (1.3).
MAX_ERROR_GROWTH = 0.25
MAX_ERROR_PX = 4.0


def _should_adopt(old_stats, old_err, new_stats, new_err):
    """
    Whether the registered model replaces the one the mapper produced.

    image_registrator can always add frames - if it has to, it will force a pose
    that no longer agrees with the rest of the solve, and the whole camera
    starts to wobble. So a gain in frames is necessary but not sufficient: the
    mean reprojection error must also stay where it was, within a quarter, and
    under MAX_ERROR_PX in absolute terms.

    Either error may be None when COLMAP could not tell us; then frame count is
    all there is to go on. Returns (adopt, reason) - the reason is logged either
    way, so the artist can see what the tool decided and why.
    """
    old_imgs = old_stats[0] if old_stats else 0
    new_imgs = new_stats[0] if new_stats else 0

    if new_imgs <= old_imgs:
        return False, ("registering added no frames (%d, was %d)" % (new_imgs, old_imgs))

    if old_err is None or new_err is None:
        return True, ("%d frames instead of %d; reprojection error unknown, so the "
                      "frame count decided it" % (new_imgs, old_imgs))

    if new_err > old_err * (1.0 + MAX_ERROR_GROWTH):
        return False, ("the extra frames pushed the reprojection error from %.3f to "
                       "%.3f px, more than the %d%% it is allowed to grow"
                       % (old_err, new_err, int(MAX_ERROR_GROWTH * 100)))

    if new_err > MAX_ERROR_PX:
        return False, ("the reprojection error would be %.3f px, over the %.1f px "
                       "a usable track stays under" % (new_err, MAX_ERROR_PX))

    return True, ("%d frames instead of %d, reprojection error %.3f px (was %.3f)"
                  % (new_imgs, old_imgs, new_err, old_err))


def frame_ranges(numbers, max_ranges=12):
    """
    [1017, 1018, 1019, 1025] -> '1017-1019, 1025'.

    Artists read a shot as ranges, not as a list of every frame, and a solve can
    easily skip fifty of them; long lists are cut off rather than filling the log.
    """
    nums = sorted(set(int(n) for n in numbers))
    if not nums:
        return ""
    runs = [[nums[0], nums[0]]]
    for n in nums[1:]:
        if n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    shown = runs[:max_ranges]
    text = ", ".join(str(a) if a == b else "%d-%d" % (a, b) for a, b in shown)
    if len(runs) > len(shown):
        text += ", and %d more" % (len(runs) - len(shown))
    return text
