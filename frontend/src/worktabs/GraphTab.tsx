import { Tab } from "../types";
import GraphView from "../views/GraphView";

export default function GraphTab({ tab: _tab }: { tab: Tab }) {
  return <GraphView mode="display" canvasHeight={460} />;
}
