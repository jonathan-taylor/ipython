# -*- coding: utf-8 -*-
"""
R related magics.

Author:
* Jonathan Taylor

"""

import sys
import tempfile
from glob import glob
from shutil import rmtree
from getopt import getopt

# numpy and rpy2 imports

import numpy as np

import rpy2.rinterface as ri
import rpy2.robjects as ro
from rpy2.robjects.numpy2ri import numpy2ri
ro.conversion.py2ri = numpy2ri

# IPython imports

from IPython.core.displaypub import publish_display_data
from IPython.core.magic import (Magics, magics_class, cell_magic, line_magic,
                                line_cell_magic)
from IPython.testing.skipdoctest import skip_doctest
from IPython.core.magic_arguments import (
    argument, magic_arguments, parse_argstring
)

@magics_class
class RMagics(Magics):

    def __init__(self, shell, Rconverter=np.asarray,
                 pyconverter=np.asarray):
        super(RMagics, self).__init__(shell)
        ri.set_writeconsole(self.write_console)

        # the embedded R process from rpy2
        self.r = ro.R()
        self.output = []
        self.Rconverter = Rconverter
        self.pyconverter = pyconverter

    def eval(self, line):
        try:
            return ri.baseenv['eval'](ri.parse(line))
        except ri.RRuntimeError as msg:
            self.output.append('ERROR parsing "%s": %s\n' % (line, msg))
            pass

    def write_console(self, output):
        '''
        A hook to capture R's stdout.
        '''
        self.output.append(output)

    def flush(self):
        value = ''.join([s.decode('utf-8') for s in self.output])
        self.output = []
        return value

    @line_magic
    def Rpush(self, line):
        '''
        A line-level magic for R that pushes
        variables from python to rpy2. 

        Parameters
        ----------

        line: input

              A white space separated string of 
              names of objects in the python name space to be 
              assigned to objects of the same name in the
              R name space. 

        '''

        inputs = line.split(' ')
        for input in inputs:
            self.r.assign(input, self.pyconverter(self.shell.user_ns[input]))

    @line_magic
    def Rpull(self, line):
        '''
        A line-level magic for R that pushes
        variables from python to rpy2. 

        Parameters
        ----------

        line: output

              A white space separated string of 
              names of objects in the R name space to be 
              assigned to objects of the same name in the
              python name space. 

        Notes
        -----

        Beware that R names can have '.' so this is not fool proof.
        To avoid this, don't name your R objects with '.'s...

        '''
        outputs = line.split(' ')
        for output in outputs:
                self.shell.push({output:self.Rconverter(self.r(output))})


    @magic_arguments()
    @argument(
        '-i', '--input', action='append',
        help='Names of input variable from shell.user_ns to be assigned to R variables of the same names after calling self.pyconverter. Multiple names can be passed separated only by commas with no whitespace.' 
        )
    @argument(
        '-o', '--output', action='append',
        help='Names of variables to be pushed from rpy2 to shell.user_ns after executing cell body and applying self.Rconverter. Multiple names can be passed separated only by commas with no whitespace.'
        )
    @argument(
        '-w', '--width', type=int,
        help='Width of png plotting device sent as an argument to *png* in R.'
        )
    @argument(
        '-h', '--height', type=int,
        help='Height of png plotting device sent as an argument to *png* in R.'
        )
    
    @argument(
        '-u', '--units', type=int,
        help='Units of png plotting device sent as an argument to *png* in R. One of ["px", "in", "cm", "mm"].'
        )
    @argument(
        '-p', '--pointsize', type=int,
        help='Pointsize of png plotting device sent as an argument to *png* in R.'
        )
    @argument(
        '-b', '--bg', 
        help='Background of png plotting device sent as an argument to *png* in R.'
        )
    @argument(
        'code', 
        nargs='*',
        )
    @line_cell_magic
    def R(self, line, cell=None):
        '''
        A line_cell_magic for R that executes
        some code in R (evaluating it with rpy2) and 
        stores some of the results
        in the ipython shell.

        If the cell is None, the resulting value is returned, 
        after conversion with self.Rconverter
        unless the line has contents that are published to the ipython
        notebook (i.e. plots are create or something is printed to 
        R's stdout() connection).

        If the cell is not None, the magic returns None.

        '''

        args = parse_argstring(self.R, line)

        # arguments 'code' in line are prepended to 
        # the cell lines
        if cell is None:
            lines = []
            return_output = True
        else:
            lines = cell.split('\n')
            return_output = False

        lines = args.code + lines

        if args.input:
            for input in ','.join(args.input).split(','):
                self.r.assign(input, self.pyconverter(self.shell.user_ns[input]))

        png_argdict = dict([(n, getattr(args, n)) for n in ['units', 'height', 'width', 'bg', 'pointsize']])
        png_args = ','.join(['%s=%s' % (o,v) for o, v in png_argdict.items() if v is not None])
        # execute the R code in a temporary directory 

        tmpd = tempfile.mkdtemp()
        self.r('png("%s/Rplots%%03d.png",%s)' % (tmpd, png_args))
        result = [self.eval(line) for line in lines]
        self.r('dev.off()')

        # read out all the saved .png files

        images = [file(imgfile).read() for imgfile in glob("%s/Rplots*png" % tmpd)]
        
        # now publish the images
        # mimicking IPython/zmq/pylab/backend_inline.py
        fmt = 'png'
        mimetypes = { 'png' : 'image/png', 'svg' : 'image/svg+xml' }
        mime = mimetypes[fmt]

        published = False
        # publish the printed R objects, if any
        flush = self.flush()
        if flush:
            published = True
            publish_display_data('RMagic.R', {'text/plain':flush})

        # flush text streams before sending figures, helps a little with output                                                                
        for image in images:
            published = True
            # synchronization in the console (though it's a bandaid, not a real sln)                           
            sys.stdout.flush(); sys.stderr.flush()
            publish_display_data(
                'RMagic.R',
                {mime : image}
            )
        value = {}

        # try to turn every output into a numpy array
        # this means that output are assumed to be castable
        # as numpy arrays

        if args.output:
            for output in ','.join(args.output).split(','):
                # with self.shell, we assign the values to variables in the shell 
                self.shell.push({output:self.Rconverter(self.r(output))})

        # kill the temporary directory
        rmtree(tmpd)

        # if there was a single line, return its value
        # converted to a python object

        if return_output and not published:
            if len(lines) > 1:
                return [self.Rconverter(rr) for rr in result]
            elif lines:
                return self.Rconverter(result[0])
            return None

_loaded = False
def load_ipython_extension(ip):
    """Load the extension in IPython."""
    global _loaded
    if not _loaded:
        ip.register_magics(RMagics)
        _loaded = True

