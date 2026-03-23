from ncl_agency_runtime.fpc.helix_news.fluency_engine import (
    FluencyEngine, SegmentPlan, SubClipPlan, SidebarItem,
)

plan = SegmentPlan("test", 15.0, [SubClipPlan(
    0, 0.0, 15.0, 15, "Test prompt",
    [
        SidebarItem("SEGMENT", "TEST", "header"),
        SidebarItem("#1", "Topic Name", "topic"),
        SidebarItem("Confidence", "82%", "metric"),
    ],
)], 0.0)

f = FluencyEngine()
vf = f.build_sidebar_drawtext_filters(plan)

print("Filter length:", len(vf))
print(vf[:300])
print("---")

# Validate escaping
assert "enable=between" in vf, "FAIL: enable should be unquoted"
assert "enable='between" not in vf, "FAIL: enable should NOT be quoted"
assert "C:/Windows/Fonts" in vf, "FAIL: font path wrong"
assert "C\\\\:" not in vf, "FAIL: double-escaped font path"
print("ALL CHECKS PASSED")
