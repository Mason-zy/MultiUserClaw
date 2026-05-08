import { SurfaceID, Surface as SurfaceState } from "../types/types";
import { A2uiMessageProcessor } from "../data/model-processor.js";
import { Root } from "./root.js";
export declare class Surface extends Root {
    #private;
    accessor surfaceId: SurfaceID | null;
    accessor surface: SurfaceState | null;
    accessor processor: A2uiMessageProcessor | null;
    static styles: any[];
    render(): any;
}
//# sourceMappingURL=surface.d.ts.map