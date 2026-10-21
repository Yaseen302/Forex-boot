import type {DatasetMetadata} from './types';

// Broker export eligibility is deliberately distinct from an explicitly
// acknowledged external CSV. Fixtures never become market evidence here.
export function datasetCanRun(dataset:DatasetMetadata|undefined,allowUnverified:boolean):boolean {
 if(!dataset?.valid||dataset.issues?.length||dataset.bar_count<8000)return false;
 return dataset.source==='mt5_broker_history'&&dataset.eligible
  ||dataset.source==='external_csv_unverified'&&allowUnverified;
}

export function finiteAssumption(value:string,minimum=0,maximum=100000):boolean {
 return value.trim()!==''&&Number.isFinite(Number(value))&&Number(value)>=minimum&&Number(value)<=maximum;
}
