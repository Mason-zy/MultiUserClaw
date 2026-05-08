import { Root } from "./root.js";
import { StringValue } from "../types/primitives.js";
import { ResolvedTextField } from "../types/types";
export declare class TextField extends Root {
    #private;
    accessor text: StringValue | null;
    accessor label: StringValue | null;
    accessor inputType: ResolvedTextField["type"] | null;
    static styles: any[];
    render(): any;
}
//# sourceMappingURL=text-field.d.ts.map