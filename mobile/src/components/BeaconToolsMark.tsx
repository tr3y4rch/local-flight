import Svg, { Circle, ClipPath, Defs, G, Line, Path, Rect } from "react-native-svg";

type BeaconToolsMarkProps = {
  size?: number;
  color?: string;
  windowColor?: string;
};

export function BeaconToolsMark({
  size = 18,
  color = "rgba(213,244,255,0.72)",
  windowColor = "#080c12"
}: BeaconToolsMarkProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 1024 1024" fill="none">
      <Defs>
        <ClipPath id="btmoBumpsClip">
          <Path
            d="
              M 480 52 C 700 52 900 148 900 276 C 900 406 700 500 480 500 Z
              M 480 524 C 724 524 940 632 940 750 C 940 866 724 974 480 974 Z
            "
          />
        </ClipPath>
      </Defs>

      <Path
        d="M 140 52 H 460 V 974 H 140 A 56 56 0 0 1 84 918 V 108 A 56 56 0 0 1 140 52 Z"
        fill={color}
        opacity={0.95}
      />
      <Path d="M 480 52 C 700 52 900 148 900 276 C 900 406 700 500 480 500 Z" fill={color} opacity={0.95} />
      <Path d="M 480 524 C 724 524 940 632 940 750 C 940 866 724 974 480 974 Z" fill={color} opacity={0.95} />

      {[112, 304, 582, 774].map((y) =>
        [140, 290].map((x) => <Rect key={`${x}-${y}`} x={x} y={y} width={120} height={150} rx={8} fill={windowColor} opacity={0.92} />)
      )}

      <G clipPath="url(#btmoBumpsClip)">
        <Path d="M 470 357 A 155 155 0 0 1 470 667" stroke={color} strokeWidth={18} strokeLinecap="round" fill="none" opacity={0.88} />
        <Path d="M 470 240 A 272 272 0 0 1 470 784" stroke={color} strokeWidth={14} strokeLinecap="round" fill="none" opacity={0.72} />
        <Path d="M 470 122 A 390 390 0 0 1 470 902" stroke={color} strokeWidth={11} strokeLinecap="round" fill="none" opacity={0.56} />
      </G>

      <Circle cx={470} cy={512} r={62} fill="none" stroke={color} strokeWidth={13} opacity={0.95} />
      <Circle cx={470} cy={512} r={44} fill={color} opacity={0.72} />
      <Circle cx={470} cy={512} r={16} fill={windowColor} opacity={0.9} />
      <Line x1={532} y1={512} x2={584} y2={512} stroke={color} strokeWidth={11} strokeLinecap="round" opacity={0.9} />
      <Circle cx={590} cy={512} r={11} fill={color} opacity={0.88} />
    </Svg>
  );
}
