"""Public synthetic H.264 fixture; contains no captured screen data."""
# Six synthetic 128x72 gray pictures, libx264, no B-frames or metadata SEI.
SAMPLE = bytes.fromhex(
    "000000016764000aacb4105fcb8088000003000800000301e47891350000000168ef0fcb"
    "00000165888404bffa7fe3fca7fe12bbdef479a65509cf64bbf1d605d58dc1ffa7ee37f8"
    "ca08c4dbf7800063c1a300000001419a2620a7fffed68cb02a6000000001419a4620affff"
    "ed6a550153100000001419a6620affffed6a550153000000001419a8620affffed6a5501531"
    "00000001419aa620affffed6a5501531"
)
