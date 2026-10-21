import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

const source=await fs.readFile(new URL('../src/research.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
const {datasetCanRun,finiteAssumption}=await import('data:text/javascript;base64,'+Buffer.from(outputText).toString('base64'));

test('unverified external research requires a separate acknowledgement and valid history',()=>{
 const external={valid:true,eligible:false,source:'external_csv_unverified',bar_count:8000,issues:[]};
 assert.equal(datasetCanRun(external,false),false);
 assert.equal(datasetCanRun(external,true),true);
 assert.equal(datasetCanRun({...external,valid:false},true),false);
 assert.equal(datasetCanRun({...external,issues:['Invalid instrument contract']},true),false);
 assert.equal(datasetCanRun({...external,bar_count:7999},true),false);
});

test('acknowledgement cannot turn fixtures or unknown sources into market evidence',()=>{
 const dataset={valid:true,eligible:true,source:'mt5_broker_history',bar_count:8000,issues:[]};
 assert.equal(datasetCanRun(dataset,false),true);
 assert.equal(datasetCanRun({...dataset,eligible:false},true),false);
 for(const source of ['synthetic_fixture','unverified','unrecognized'])assert.equal(datasetCanRun({...dataset,source},true),false);
});

test('costs need explicit finite nonnegative debit assumptions, including explicit zero',()=>{
 for(const value of ['',' ','-3','NaN','Infinity','1e999','100001'])assert.equal(finiteAssumption(value),false);
 for(const value of ['0','0.0001','7','100000'])assert.equal(finiteAssumption(value),true);
 assert.equal(finiteAssumption('0',.01,100000000),false);
 assert.equal(finiteAssumption('1000',.01,100000000),true);
});
