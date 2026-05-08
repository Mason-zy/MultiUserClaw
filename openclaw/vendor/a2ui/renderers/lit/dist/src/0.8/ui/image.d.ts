import { Root } from "./root.js";
import { StringValue } from "../types/primitives.js";
import { ResolvedImage } from "../types/types.js";
export declare class Image extends Root {
    #private;
    accessor url: StringValue | null;
    accessor usageHint: ResolvedImage["usageHint"] | null;
    accessor fit: "contain" | "cover" | "fill" | "none" | "scale-down" | null;
    static styles: any[];
    render(): any;
}
//# sourceMappingURL=image.d.ts.map