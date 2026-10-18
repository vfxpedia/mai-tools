#!/usr/bin/env node
import {main} from '../src/setup.mjs';
main().catch(error=>{console.error(`Codex Mods operation refused: ${error.message}.`);process.exitCode=1;});
