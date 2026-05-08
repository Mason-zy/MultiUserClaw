import { PropertyValues } from "lit";
import { Root } from "./root.js";
import { StringValue } from "../types/primitives.js";
export declare class MultipleChoice extends Root {
    #private;
    accessor description: string | null;
    accessor options: {
        label: StringValue;
        value: string;
    }[];
    accessor selections: StringValue | string[];
    static styles: any[];
    protected willUpdate(changedProperties: PropertyValues<this>): void;
    render(): any;
}
//# sourceMappingURL=multiple-choice.d.ts.map