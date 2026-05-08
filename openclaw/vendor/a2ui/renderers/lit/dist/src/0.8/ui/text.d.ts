import { Root } from "./root.js";
import { StringValue } from "../types/primitives.js";
import { ResolvedText } from "../types/types.js";
export declare class Text extends Root {
    #private;
    accessor text: StringValue | null;
    accessor usageHint: ResolvedText["usageHint"] | null;
    static styles: any[];
    render(): any;
}
//# sourceMappingURL=text.d.ts.map