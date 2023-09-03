var __index = {"config":{"lang":["en"],"separator":"[\\s\\-]+","pipeline":["stopWordFilter"]},"docs":[{"location":"index.html","title":"whl2conda","text":"<p>Generate conda packages directly from pure python wheels</p> <p>whl2conda is a command line utility to build and test conda packages generated directly from pure python wheels.</p>"},{"location":"index.html#features","title":"Features","text":"<ul> <li> <p>Performance: because it does not need to create conda environments     for building, this is much faster than solutions involving conda-build.</p> </li> <li> <p>Multiple package formats: can generate both V1 ('.tar.bz2') and V2 ('.conda')     conda package formats. Can also generate a unpacked directory tree for debugging     or additional user customization.</p> </li> <li> <p>Dependency renaming: renames pypi package dependencies to their      corresponding conda name. Automatically renames packages from known     list collected from conda-forge and supports user-specified rename     patterns as well.</p> </li> <li> <p>Project configuration: project-specific options can be saved in     project's <code>pyproject.toml</code> file.</p> </li> <li> <p>Install support: supports installing conda package into a conda     environment for testing prior to deployment.</p> </li> <li> <p>Hides pypi dependencies: if the original pypi dependencies are included in     the python dist-info included in the conda package, this can result in      problems if pip or other python packaging tools are used in the conda environment.     To avoid this, whl2conda changes these dependencies to extras.</p> </li> </ul>"},{"location":"index.html#installation","title":"Installation","text":"<p>With pip:</p> <pre><code>pip install whl2conda\n</code></pre> <p>With conda (upcoming):</p> <pre><code>conda install -c conda-forge whl2conda\n</code></pre>"},{"location":"index.html#quick-usage","title":"Quick usage","text":"<p>Generate a conda package in same directory as wheel file:</p> <pre><code>whl2conda build dist/mypackage-1.2.3-py3-none-any.whl\n</code></pre> <p>Add default tool options to <code>pyproject.toml</code></p> <p><pre><code>whl2conda config --generate-pyproject pyproject.toml\n</code></pre> Build both wheel and conda package for project:</p> <pre><code>whl2conda build --build-wheel my-project-root\n</code></pre> <p>Create python 3.10 test environment for generated conda package:</p> <pre><code>whl2conda install dist/mypackage-1.2.3.-py_0.conda --create -n testenv \\\n--extra pytest python=3.10\n</code></pre>"},{"location":"license.html","title":"License","text":"<pre><code>                             Apache License\n                       Version 2.0, January 2004\n                    http://www.apache.org/licenses/\n</code></pre> <p>TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION</p> <ol> <li> <p>Definitions.</p> <p>\"License\" shall mean the terms and conditions for use, reproduction,   and distribution as defined by Sections 1 through 9 of this document.</p> <p>\"Licensor\" shall mean the copyright owner or entity authorized by   the copyright owner that is granting the License.</p> <p>\"Legal Entity\" shall mean the union of the acting entity and all   other entities that control, are controlled by, or are under common   control with that entity. For the purposes of this definition,   \"control\" means (i) the power, direct or indirect, to cause the   direction or management of such entity, whether by contract or   otherwise, or (ii) ownership of fifty percent (50%) or more of the   outstanding shares, or (iii) beneficial ownership of such entity.</p> <p>\"You\" (or \"Your\") shall mean an individual or Legal Entity   exercising permissions granted by this License.</p> <p>\"Source\" form shall mean the preferred form for making modifications,   including but not limited to software source code, documentation   source, and configuration files.</p> <p>\"Object\" form shall mean any form resulting from mechanical   transformation or translation of a Source form, including but   not limited to compiled object code, generated documentation,   and conversions to other media types.</p> <p>\"Work\" shall mean the work of authorship, whether in Source or   Object form, made available under the License, as indicated by a   copyright notice that is included in or attached to the work   (an example is provided in the Appendix below).</p> <p>\"Derivative Works\" shall mean any work, whether in Source or Object   form, that is based on (or derived from) the Work and for which the   editorial revisions, annotations, elaborations, or other modifications   represent, as a whole, an original work of authorship. For the purposes   of this License, Derivative Works shall not include works that remain   separable from, or merely link (or bind by name) to the interfaces of,   the Work and Derivative Works thereof.</p> <p>\"Contribution\" shall mean any work of authorship, including   the original version of the Work and any modifications or additions   to that Work or Derivative Works thereof, that is intentionally   submitted to Licensor for inclusion in the Work by the copyright owner   or by an individual or Legal Entity authorized to submit on behalf of   the copyright owner. For the purposes of this definition, \"submitted\"   means any form of electronic, verbal, or written communication sent   to the Licensor or its representatives, including but not limited to   communication on electronic mailing lists, source code control systems,   and issue tracking systems that are managed by, or on behalf of, the   Licensor for the purpose of discussing and improving the Work, but   excluding communication that is conspicuously marked or otherwise   designated in writing by the copyright owner as \"Not a Contribution.\"</p> <p>\"Contributor\" shall mean Licensor and any individual or Legal Entity   on behalf of whom a Contribution has been received by Licensor and   subsequently incorporated within the Work.</p> </li> <li> <p>Grant of Copyright License. Subject to the terms and conditions of       this License, each Contributor hereby grants to You a perpetual,       worldwide, non-exclusive, no-charge, royalty-free, irrevocable       copyright license to reproduce, prepare Derivative Works of,       publicly display, publicly perform, sublicense, and distribute the       Work and such Derivative Works in Source or Object form.</p> </li> <li> <p>Grant of Patent License. Subject to the terms and conditions of       this License, each Contributor hereby grants to You a perpetual,       worldwide, non-exclusive, no-charge, royalty-free, irrevocable       (except as stated in this section) patent license to make, have made,       use, offer to sell, sell, import, and otherwise transfer the Work,       where such license applies only to those patent claims licensable       by such Contributor that are necessarily infringed by their       Contribution(s) alone or by combination of their Contribution(s)       with the Work to which such Contribution(s) was submitted. If You       institute patent litigation against any entity (including a       cross-claim or counterclaim in a lawsuit) alleging that the Work       or a Contribution incorporated within the Work constitutes direct       or contributory patent infringement, then any patent licenses       granted to You under this License for that Work shall terminate       as of the date such litigation is filed.</p> </li> <li> <p>Redistribution. You may reproduce and distribute copies of the       Work or Derivative Works thereof in any medium, with or without       modifications, and in Source or Object form, provided that You       meet the following conditions:</p> <p>(a) You must give any other recipients of the Work or       Derivative Works a copy of this License; and</p> <p>(b) You must cause any modified files to carry prominent notices       stating that You changed the files; and</p> <p>(c) You must retain, in the Source form of any Derivative Works       that You distribute, all copyright, patent, trademark, and       attribution notices from the Source form of the Work,       excluding those notices that do not pertain to any part of       the Derivative Works; and</p> <p>(d) If the Work includes a \"NOTICE\" text file as part of its       distribution, then any Derivative Works that You distribute must       include a readable copy of the attribution notices contained       within such NOTICE file, excluding those notices that do not       pertain to any part of the Derivative Works, in at least one       of the following places: within a NOTICE text file distributed       as part of the Derivative Works; within the Source form or       documentation, if provided along with the Derivative Works; or,       within a display generated by the Derivative Works, if and       wherever such third-party notices normally appear. The contents       of the NOTICE file are for informational purposes only and       do not modify the License. You may add Your own attribution       notices within Derivative Works that You distribute, alongside       or as an addendum to the NOTICE text from the Work, provided       that such additional attribution notices cannot be construed       as modifying the License.</p> <p>You may add Your own copyright statement to Your modifications and   may provide additional or different license terms and conditions   for use, reproduction, or distribution of Your modifications, or   for any such Derivative Works as a whole, provided Your use,   reproduction, and distribution of the Work otherwise complies with   the conditions stated in this License.</p> </li> <li> <p>Submission of Contributions. Unless You explicitly state otherwise,       any Contribution intentionally submitted for inclusion in the Work       by You to the Licensor shall be under the terms and conditions of       this License, without any additional terms or conditions.       Notwithstanding the above, nothing herein shall supersede or modify       the terms of any separate license agreement you may have executed       with Licensor regarding such Contributions.</p> </li> <li> <p>Trademarks. This License does not grant permission to use the trade       names, trademarks, service marks, or product names of the Licensor,       except as required for reasonable and customary use in describing the       origin of the Work and reproducing the content of the NOTICE file.</p> </li> <li> <p>Disclaimer of Warranty. Unless required by applicable law or       agreed to in writing, Licensor provides the Work (and each       Contributor provides its Contributions) on an \"AS IS\" BASIS,       WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or       implied, including, without limitation, any warranties or conditions       of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A       PARTICULAR PURPOSE. You are solely responsible for determining the       appropriateness of using or redistributing the Work and assume any       risks associated with Your exercise of permissions under this License.</p> </li> <li> <p>Limitation of Liability. In no event and under no legal theory,       whether in tort (including negligence), contract, or otherwise,       unless required by applicable law (such as deliberate and grossly       negligent acts) or agreed to in writing, shall any Contributor be       liable to You for damages, including any direct, indirect, special,       incidental, or consequential damages of any character arising as a       result of this License or out of the use or inability to use the       Work (including but not limited to damages for loss of goodwill,       work stoppage, computer failure or malfunction, or any and all       other commercial damages or losses), even if such Contributor       has been advised of the possibility of such damages.</p> </li> <li> <p>Accepting Warranty or Additional Liability. While redistributing       the Work or Derivative Works thereof, You may choose to offer,       and charge a fee for, acceptance of support, warranty, indemnity,       or other liability obligations and/or rights consistent with this       License. However, in accepting such obligations, You may act only       on Your own behalf and on Your sole responsibility, not on behalf       of any other Contributor, and only if You agree to indemnify,       defend, and hold each Contributor harmless for any liability       incurred by, or claims asserted against, such Contributor by reason       of your accepting any such warranty or additional liability.</p> </li> </ol> <p>END OF TERMS AND CONDITIONS</p> <p>APPENDIX: How to apply the Apache License to your work.</p> <pre><code>  To apply the Apache License to your work, attach the following\n  boilerplate notice, with the fields enclosed by brackets \"{}\"\n  replaced with your own identifying information. (Don't include\n  the brackets!)  The text should be enclosed in the appropriate\n  comment syntax for the file format. We also recommend that a\n  file or class name and description of purpose be included on the\n  same \"printed page\" as the copyright notice for easier\n  identification within third-party archives.\n</code></pre> <p>Copyright 2023   Christopher Barber</p> <p>Licensed under the Apache License, Version 2.0 (the \"License\");    you may not use this file except in compliance with the License.    You may obtain a copy of the License at</p> <pre><code>   http://www.apache.org/licenses/LICENSE-2.0\n</code></pre> <p>Unless required by applicable law or agreed to in writing, software    distributed under the License is distributed on an \"AS IS\" BASIS,    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.    See the License for the specific language governing permissions and    limitations under the License.</p>"},{"location":"cli/whl2conda-build.html","title":"whl2conda build","text":""},{"location":"cli/whl2conda-build.html#whl2conda-build","title":"whl2conda build","text":""},{"location":"cli/whl2conda-build.html#usage","title":"Usage","text":"<pre><code>usage: whl2conda build &lt;wheel&gt; [options]\n       whl2conda build [&lt;project-root&gt;] [options]\n</code></pre> <p>Generates a conda package from a pure python wheel</p>"},{"location":"cli/whl2conda-build.html#input-options","title":"Input options","text":"<pre><code>  [&lt;wheel&gt; | &lt;project-root&gt;]\n            Either path to a wheel file to convert or a project root\n            directory containing a pyproject.toml or setup.py file.\n  --project-root &lt;dir&gt;, --root &lt;dir&gt;\n            Project root directory. This is a directory containing either a\n            pyproject.toml or a (deprecated) setup.py file. This option may\n            not be used if the project directory was given as the positional\n            argument.\n\n            If not specified, the project root will be located by searching\n            the wheel directory and its parent directories, or if no wheel\n            given, will default to the current directory.\n  -w &lt;dir&gt;, --wheel-dir &lt;dir&gt;\n            Location of wheel directory. Defaults to dist/ subdirectory of \n            project.\n  --ignore-pyproject\n            Ignore settings from pyproject.toml file, if any\n</code></pre>"},{"location":"cli/whl2conda-build.html#output-options","title":"Output options","text":"<pre><code>  --out-dir &lt;dir&gt;, --out &lt;dir&gt;\n            Output directory for conda package. Defaults to wheel directory\n            or else project dist directory.\n  --overwrite\n            Overwrite existing output files.\n  --format {V1,tar.bz2,V2,conda,tree}, --out-format {V1,tar.bz2,V2,conda,tree}\n            Output package format (None)\n  --build-wheel\n            Build wheel\n</code></pre>"},{"location":"cli/whl2conda-build.html#override-options","title":"Override options","text":"<pre><code>  --name &lt;package-name&gt;\n            Override package name\n  -R &lt;pip-name&gt; &lt;conda-name&gt;, --dependency-rename &lt;pip-name&gt; &lt;conda-name&gt;\n            Rename pip dependency for conda. May be specified muliple times.\n  -A &lt;conda-dep&gt;, --add-dependency &lt;conda-dep&gt;\n            Add an additional conda dependency. May be specified multiple times.\n  -D &lt;pip-name&gt;, --drop-dependency &lt;pip-name&gt;\n            Drop dependency with given name from conda dependency list.\n            May be specified multiple times.\n  -K, --keep-pip-dependencies\n            Retain pip dependencies in python dist_info of conda package.\n  --python &lt;version-spec&gt;\n            Set/override python dependency.\n</code></pre>"},{"location":"cli/whl2conda-build.html#help-and-debug-options","title":"Help and debug options","text":"<pre><code>  -n, --dry-run\n            Do not write any files.\n  --batch, --not-interactive\n            Batch mode - disable interactive prompts.\n  --yes     Answer 'yes' or choose default to all interactive questions\n  -v, --verbose\n            Increase verbosity.\n  -q, --quiet\n            Less verbose output\n  -h, -?, --help\n            Show usage and exit.\n</code></pre>"},{"location":"cli/whl2conda-config.html","title":"whl2conda config","text":""},{"location":"cli/whl2conda-config.html#whl2conda-config","title":"whl2conda config","text":""},{"location":"cli/whl2conda-config.html#usage","title":"Usage","text":"<pre><code>usage: whl2conda config [-h] [--generate-pyproject [&lt;dir-or-toml&gt;]]\n                        [--update-std-renames [&lt;file&gt;]] [-n]\n</code></pre> <p>whl2conda configuration</p>"},{"location":"cli/whl2conda-config.html#optional-arguments","title":"optional arguments","text":"<pre><code>  -h, --help\n            show this help message and exit\n  --generate-pyproject [&lt;dir-or-toml&gt;]\n            Add default whl2conda tool entries to a pyproject file. \n            If argument is a directory entries will be added to \n            `pyproject.toml` in that directory. If argument ends\n            with suffix '.toml', that file will be updated. If\n            the argument is omitted or set to `out` the generated entry \n            will be written to stdout. Other values will result in an error.\n            This will create file if it does not already exist.\n            It will not overwrite existing entires.\n  --update-std-renames [&lt;file&gt;]\n            Update list of standard pypi to conda renames from internet and exit.\n            If a &lt;file&gt; is not named, the default copy will be updated at\n            /Users/Christopher.Barber/Library/Caches/whl2conda/stdrename.json.\n  -n, --dry-run\n            Do not write any files.\n</code></pre>"},{"location":"cli/whl2conda-install.html","title":"whl2conda install","text":""},{"location":"cli/whl2conda-install.html#whl2conda-install","title":"whl2conda install","text":""},{"location":"cli/whl2conda-install.html#usage","title":"Usage","text":"<pre><code>usage: whl2conda install (-p &lt;env-path&gt; | -n &lt;env-name&gt;) &lt;package-file&gt; [options]\n       whl2conda install --conda-bld &lt;package-file&gt; [options]\n</code></pre> <p>Install a conda package file</p> <p>This can be used to install a conda package file (generated by <code>whl2conda build</code>) either into a conda environment (for testing) or into your local conda build directory.</p>"},{"location":"cli/whl2conda-install.html#positional-arguments","title":"positional arguments","text":"<pre><code>  &lt;package-file&gt;\n            Conda package file to be installed\n            Must have extension .conda or .tar.bz2\n</code></pre>"},{"location":"cli/whl2conda-install.html#optional-arguments","title":"optional arguments","text":"<pre><code>  -h, --help\n            show this help message and exit\n</code></pre>"},{"location":"cli/whl2conda-install.html#target-choose-one","title":"Target (choose one)","text":"<pre><code>  -p &lt;env-path&gt;, --prefix &lt;env-path&gt;\n            Path to target conda environment\n  -n &lt;env-name&gt;, --name &lt;env-name&gt;\n            Name of target conda enviroment\n  --conda-bld\n            Install into local conda-bld\n</code></pre>"},{"location":"cli/whl2conda-install.html#environment-options","title":"Environment options","text":"<pre><code>  These options can be used with -n/-p when install into\n  a conda environment. They are otherwise ignored.\n\n  --create  Create environment if it does not exist.\n  --only-deps\n            Only install package dependencies, not the package itself.\n  --mamba   Use mamba instead of conda for install actions\n  --extra ...\n            All the remaining arguments after this flat will be passed\n            to `conda install` or `conda create`. This can be used to add\n            additional dependencies for testing.\n</code></pre>"},{"location":"cli/whl2conda-install.html#common-options","title":"Common options","text":"<pre><code>  --dry-run\n            Display operations but don't actually install\n  --yes     Answer yes to prompts.\n</code></pre>"},{"location":"cli/whl2conda.html","title":"wl2conda","text":""},{"location":"cli/whl2conda.html#whl2conda","title":"whl2conda","text":""},{"location":"cli/whl2conda.html#usage","title":"Usage","text":"<pre><code>usage: whl2conda [options] &lt;command&gt; ...\n</code></pre> <p>Utility for building and testing conda package generated directly from a python wheel.</p> <p>See <code>whl2conda build --help</code> for more information.</p>"},{"location":"cli/whl2conda.html#optional-arguments","title":"optional arguments","text":"<pre><code>  -h, --help\n            show this help message and exit\n  --version\n            show program's version number and exit\n</code></pre>"},{"location":"cli/whl2conda.html#commands","title":"Commands","text":"<pre><code>  &lt;command&gt;\n    build   builds a conda package from a python wheel\n    config  configure whl2conda\n    install\n            install conda package file with dependencies\n</code></pre>"}]}